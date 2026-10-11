"""Background jobs: starting, streaming, and actually stopping.

The valuable assertions here are the ones a serial `subprocess.run` could not
satisfy:

* output written *later* is returned *later*, without the first read having had to
  wait for the process to exit -- otherwise nothing is being streamed and the
  whole feature is a slower `execute_command`;
* a read returns only what is new, so polling a job from a turn loop does not
  re-send the same log into the conversation every turn;
* a killed job is *stopped*, including the child that holds the port, and the kill
  does not block for the lifetime of the command it is killing.

Real processes are used rather than a fake `Popen`, because the things most likely
to be wrong -- a reader thread that never sees the last line, a kill that only
reaches the shell, a job that waits forever on stdin nobody will write -- are all
properties of the operating system rather than of this code.
"""

from __future__ import annotations

import asyncio
import sys
import time

import pytest

import tonyagent.tools  # noqa: F401  -- importing registers every tool
from tonyagent.folder import folder_manager
from tonyagent.sandbox import get_shared_sandbox_manager
from tonyagent.sandbox.base import SandboxConfig, SandboxStatus
from tonyagent.tools import tool_registry
from tonyagent.tools import shell_tools
from tonyagent.tools.base import ToolResultStatus
from tonyagent.tools.jobs import JobStatus, jobs_registry


def tool(name: str):
    found = tool_registry.get(name)
    assert found is not None, f"{name} is not registered"
    return found


def py(code: str) -> str:
    """A Python one-liner as a shell command, quoted for either platform.

    ``sys.executable`` rather than ``python``: the interpreter running the tests
    is the one guaranteed to exist, and on Windows a bare ``python`` may be the
    Microsoft Store shim that opens a browser instead.
    """
    assert '"' not in code, "the quoting below cannot survive a double quote"
    return f'"{sys.executable}" -c "{code}"'


@pytest.fixture(autouse=True)
def clean_registry():
    """No job outlives the test that started it, including the killed ones."""
    jobs_registry.reset()
    yield
    jobs_registry.reset()


@pytest.fixture
def host(monkeypatch, tmp_path):
    """Host execution, and a project folder to run in."""
    monkeypatch.setattr(shell_tools, "_HOST_EXECUTION", True)
    monkeypatch.setattr(folder_manager, "_current_folder", tmp_path)
    return tmp_path


def wait_for(job, timeout: float = 20.0):
    """Wait for a job to finish, then let its readers drain the tail."""
    deadline = time.monotonic() + timeout
    while job.running and time.monotonic() < deadline:
        time.sleep(0.02)
    job.drain()
    return job


class FakeIsolatingBackend:
    """Stands in for a running container, which is where jobs cannot go."""

    provides_isolation = True

    def __init__(self):
        self.status = SandboxStatus.RUNNING
        self.config = SandboxConfig(enable_network=True)

    async def execute_command(self, command, cwd="/workspace", timeout=30):  # pragma: no cover
        raise AssertionError("a background command must not have been sent to the sandbox")


# --- the registry: output ----------------------------------------------------


def test_a_finished_job_reports_its_output_and_exit_code(host):
    job = jobs_registry.start(py("print('hello')"), host)
    wait_for(job)

    out, err, _, _ = job.read()
    assert "hello" in out
    assert err == ""
    assert job.returncode == 0
    assert job.status is JobStatus.EXITED
    assert not job.running


def test_a_non_zero_exit_is_reported(host):
    job = jobs_registry.start(py("import sys; sys.exit(3)"), host)
    wait_for(job)

    assert job.returncode == 3
    assert job.status is JobStatus.EXITED


def test_stderr_is_kept_apart_from_stdout(host):
    job = jobs_registry.start(py("import sys; sys.stderr.write('bad\\n')"), host)
    wait_for(job)

    out, err, _, _ = job.read()
    assert out == ""
    assert "bad" in err


def test_output_is_only_returned_once(host):
    """The property that makes polling affordable.

    Re-sending the whole log each poll would put the same text into the
    conversation over and over, paid for on every turn.
    """
    job = jobs_registry.start(py("print('once')"), host)
    wait_for(job)

    first, _, _, _ = job.read()
    second, _, _, _ = job.read()

    assert "once" in first
    assert second == "", f"the same output came back twice: {second!r}"


def test_output_written_later_is_available_later(host):
    """Streamed, not buffered until exit.

    The job prints one line, waits, then prints another. If the reader only ran at
    exit the first line would not be visible while the job was still running --
    which is the difference between watching a build and waiting for one.
    """
    code = (
        "import time; print('first', flush=True); "
        "time.sleep(1.0); print('second', flush=True)"
    )
    job = jobs_registry.start(py(code), host)

    seen = ""
    deadline = time.monotonic() + 10
    while "first" not in seen and time.monotonic() < deadline:
        chunk, _ = job.stdout.read()
        seen += chunk
        time.sleep(0.02)

    assert "first" in seen, f"nothing was streamed while the job ran: {seen!r}"
    assert "second" not in seen, "the reader waited for exit instead of streaming"
    assert job.running, "the first line only appeared after the job had finished"

    wait_for(job)
    rest, _ = job.stdout.read()
    assert "second" in seen + rest


def test_a_job_cannot_hang_waiting_for_input(host):
    """stdin is closed, so a prompting command sees EOF instead of blocking.

    A background command that decided to ask a question would otherwise sit on a
    pipe nobody will ever write to, and the job would look hung rather than like
    it was waiting for an answer that cannot come.
    """
    job = jobs_registry.start(py("import sys; print(len(sys.stdin.read()))"), host)

    wait_for(job, timeout=15)

    assert not job.running, "the job is still waiting on stdin"
    out, _, _, _ = job.read()
    assert "0" in out


def test_the_buffer_is_bounded_and_reports_what_it_dropped(host, monkeypatch):
    """A job that logs for an hour must not be able to exhaust memory.

    And it must not do it quietly: dropped text is counted and reported, so a gap
    in the output is never presented as continuous output.
    """
    from tonyagent.tools import jobs as jobs_module

    monkeypatch.setattr(jobs_module, "MAX_BUFFER_CHARS", 40)
    job = jobs_registry.start(py("print('x' * 500)"), host)
    wait_for(job)

    out, _, dropped, _ = job.read()

    assert dropped > 0, "text was dropped from the buffer without being counted"
    assert len(out) <= 41, f"the buffer was not bounded: kept {len(out)} chars"


# --- the registry: lifecycle -------------------------------------------------


def test_a_running_job_is_killed_quickly(host):
    """Killed, and quickly: the kill must not wait out the command's own lifetime."""
    job = jobs_registry.start(py("import time; time.sleep(30)"), host)
    time.sleep(0.4)
    assert job.running, "the job exited before it could be killed"

    start = time.monotonic()
    jobs_registry.kill(job.id)
    elapsed = time.monotonic() - start

    assert not job.running
    assert job.status is JobStatus.KILLED
    assert elapsed < 10, f"the kill took {elapsed:.1f}s, which is the command's own sleep"


def test_killing_a_finished_job_does_not_relabel_it(host):
    """A job that exited on its own was not killed.

    "The user stopped it" and "it finished" have different next steps, and the
    return code alone cannot tell them apart.
    """
    job = jobs_registry.start(py("print('done')"), host)
    wait_for(job)

    jobs_registry.kill(job.id)

    assert job.status is JobStatus.EXITED
    assert job.returncode == 0


def test_ids_are_unique_and_look_up_the_right_job(host):
    first = jobs_registry.start(py("print('alpha')"), host)
    second = jobs_registry.start(py("print('beta')"), host)

    assert first.id != second.id
    assert jobs_registry.get(first.id) is first
    assert jobs_registry.get(second.id) is second


def test_an_unknown_id_is_not_a_job(host):
    assert jobs_registry.get("nope") is None
    assert jobs_registry.get("") is None
    assert jobs_registry.get(None) is None


def test_jobs_are_listed_oldest_first(host):
    first = jobs_registry.start(py("print(1)"), host)
    time.sleep(0.02)
    second = jobs_registry.start(py("print(2)"), host)

    assert [job.id for job in jobs_registry.all()] == [first.id, second.id]


def test_shutdown_stops_everything_and_forgets_it(host):
    """The orphan guard: the core is a child process and jobs are its children.

    Without this, an exit leaves every job running with nothing left that knows
    about them -- servers holding ports the user has to find and kill by hand.
    """
    first = jobs_registry.start(py("import time; time.sleep(30)"), host)
    second = jobs_registry.start(py("import time; time.sleep(30)"), host)
    time.sleep(0.4)

    jobs_registry.shutdown()

    assert not first.running
    assert not second.running
    assert jobs_registry.all() == []


def test_finished_jobs_do_not_accumulate_without_limit(host, monkeypatch):
    """A finished job still holds its buffers, so the history has to be bounded.

    Only finished ones: a running job is never pruned, because that would take
    away the id needed to stop it.
    """
    from tonyagent.tools import jobs as jobs_module

    monkeypatch.setattr(jobs_module, "MAX_FINISHED_JOBS", 2)

    long_lived = jobs_registry.start(py("import time; time.sleep(30)"), host)
    time.sleep(0.3)

    finished = []
    for _ in range(4):
        job = jobs_registry.start(py("print('done')"), host)
        wait_for(job)
        finished.append(job.id)

    remaining = {job.id for job in jobs_registry.all()}

    assert long_lived.id in remaining, "a running job was pruned"
    assert finished[-1] in remaining, "the most recent finished job was pruned"
    assert finished[0] not in remaining, "the oldest finished job was kept"
    assert len(remaining) == 3, f"expected 2 finished and 1 running: {remaining}"

    jobs_registry.kill(long_lived.id)


# --- the tools ---------------------------------------------------------------


async def test_job_list_says_so_when_there_are_none(host):
    result = await tool("job_list").execute()
    assert result.status is ToolResultStatus.SUCCESS
    assert "No background jobs" in result.output


async def test_a_job_started_through_execute_command_is_read_and_reported(host):
    """The end-to-end path: start with execute_command, finish with the job tools."""
    started = await tool("execute_command").execute(
        py("print('served')"), background=True
    )

    assert started.status is ToolResultStatus.SUCCESS, started.error
    assert "Started job" in started.output

    jobs = jobs_registry.all()
    assert len(jobs) == 1, "execute_command(background=True) did not start exactly one job"
    job = jobs[0]

    listed = await tool("job_list").execute()
    assert job.id in listed.output
    assert "running" in listed.output or "exited" in listed.output

    waited = await tool("job_output").execute(
        job_id=job.id, wait=True, timeout_ms=10000
    )
    assert waited.status is ToolResultStatus.SUCCESS
    assert "served" in waited.output
    assert "exited(0)" in waited.output


async def test_job_output_returns_nothing_new_on_a_second_read(host):
    said = "hello from the job"
    await tool("execute_command").execute(py(f"print('{said}')"), background=True)
    job = jobs_registry.all()[0]

    first = await tool("job_output").execute(job_id=job.id, wait=True, timeout_ms=10000)
    second = await tool("job_output").execute(job_id=job.id)

    assert said in first.output
    assert said not in second.output, "the same output was returned twice"
    assert "no new output" in second.output


async def test_job_output_wait_gives_up_at_the_timeout(host):
    """A wait that never returns is a hang; it has to end and say where things are."""
    await tool("execute_command").execute(
        py("import time; time.sleep(30)"), background=True
    )
    job = jobs_registry.all()[0]

    start = time.monotonic()
    result = await tool("job_output").execute(job_id=job.id, wait=True, timeout_ms=150)
    elapsed = time.monotonic() - start

    assert result.status is ToolResultStatus.SUCCESS
    assert "running" in result.output, "the job was not reported as still running"
    assert elapsed < 10, f"the timeout took {elapsed:.1f}s"


async def test_job_output_can_be_asked_without_waiting(host):
    await tool("execute_command").execute(
        py("import time; time.sleep(30)"), background=True
    )
    job = jobs_registry.all()[0]

    start = time.monotonic()
    result = await tool("job_output").execute(job_id=job.id)
    elapsed = time.monotonic() - start

    assert result.status is ToolResultStatus.SUCCESS
    assert elapsed < 5, "job_output blocked without being asked to wait"


async def test_job_kill_stops_a_running_job(host):
    await tool("execute_command").execute(
        py("import time; time.sleep(30)"), background=True
    )
    job = jobs_registry.all()[0]

    result = await tool("job_kill").execute(job_id=job.id)

    assert result.status is ToolResultStatus.SUCCESS
    assert "Stopped" in result.output
    assert not job.running
    assert job.status is JobStatus.KILLED


async def test_job_kill_on_a_finished_job_says_so_rather_than_failing(host):
    """It is already stopped, which is what was asked for -- not an error."""
    await tool("execute_command").execute(py("print('quick')"), background=True)
    job = jobs_registry.all()[0]
    await tool("job_output").execute(job_id=job.id, wait=True, timeout_ms=10000)

    result = await tool("job_kill").execute(job_id=job.id)

    assert result.status is ToolResultStatus.SUCCESS
    assert "already" in result.output


@pytest.mark.parametrize("name", ["job_output", "job_kill"])
async def test_an_unknown_job_id_names_the_ones_that_exist(host, name):
    """An id is opaque, so "no such job" without the real ones is a dead end."""
    started = await tool("execute_command").execute(py("print('x')"), background=True)
    assert started.status is ToolResultStatus.SUCCESS
    real = jobs_registry.all()[0].id

    arguments = {"job_id": "deadbeef"}
    result = await tool(name).execute(**arguments)

    assert result.status is ToolResultStatus.ERROR
    assert "deadbeef" in result.error
    assert real in result.error, "the refusal did not say which ids do exist"


# --- where a job may run -----------------------------------------------------


async def test_background_is_refused_in_the_sandbox(host, monkeypatch):
    """A container runs one command per request and keeps no handle afterwards.

    Asserted at the tool, because the refusal has to happen *before* anything is
    started: a job that leaks a process the registry does not know about is worse
    than one that never ran.
    """
    monkeypatch.setattr(shell_tools, "_HOST_EXECUTION", False)
    monkeypatch.setattr(shell_tools.settings.tools, "fallback_to_local", False)
    manager = get_shared_sandbox_manager()
    manager._backend = FakeIsolatingBackend()
    try:
        result = await tool("execute_command").execute(
            "python --version", background=True
        )
    finally:
        manager._backend = None

    assert result.status is ToolResultStatus.ERROR
    assert "background job" in result.error
    assert "Full" in result.error, "the refusal did not name the way to make it work"
    assert jobs_registry.all() == [], "a job was started despite the refusal"


async def test_background_works_through_the_fallback_setting(host, monkeypatch):
    """`tools.fallback_to_local` is the *setting* accepting host execution.

    A different decision from the permission rung, and it has to work here for the
    same reason it works for a foreground command.
    """
    monkeypatch.setattr(shell_tools, "_HOST_EXECUTION", False)
    monkeypatch.setattr(shell_tools.settings.tools, "fallback_to_local", True)
    get_shared_sandbox_manager()._backend = None

    result = await tool("execute_command").execute(py("print('fallback')"), background=True)

    assert result.status is ToolResultStatus.SUCCESS, result.error
    assert len(jobs_registry.all()) == 1


async def test_a_denied_command_is_denied_in_the_background_too(host, monkeypatch):
    """The allow-list and denylist run before anything is started.

    A background job must not be a way round the gates, which is the whole reason
    the job path is inside `execute_command` rather than a second shell tool.
    """
    monkeypatch.setattr(shell_tools.settings.tools, "fallback_to_local", False)
    monkeypatch.setattr(shell_tools, "_ALLOWLIST_BYPASS", False)

    result = await tool("execute_command").execute(
        "curl http://example.com", background=True
    )

    assert result.status is ToolResultStatus.ERROR
    assert "not allowed" in result.error.lower()
    assert jobs_registry.all() == []


# --- the shape of the tools themselves ---------------------------------------


def test_the_job_tools_need_no_project_folder():
    """They read process state, not the workspace -- like the network tools."""
    for name in ("job_list", "job_output", "job_kill"):
        tool_obj = tool(name)
        assert tool_obj.folder_required is False, name
        assert tool_obj.destructive is False, name
        assert tool_obj.requires_confirmation is False, name


def test_job_list_takes_no_arguments():
    tool_obj = tool("job_list")
    assert tool_obj.parameters["properties"] == {}
    assert tool_obj.required == []
    ok, error = tool_obj.validate_args({})
    assert ok, error


def test_the_job_tools_reach_the_wire_intact():
    from tonyagent.api.dialects import tool_to_openai
    from tonyagent.providers.base import ToolSchema
    from tonyagent.tools.schemas import SCHEMAS_BY_NAME

    for name in ("job_list", "job_output", "job_kill"):
        schema = SCHEMAS_BY_NAME[name]
        payload = tool_to_openai(
            [ToolSchema.from_tool_schema_dict(schema).to_openai_format()]
        )[0]["function"]
        assert payload["name"] == name
        assert payload["description"].strip()
        assert isinstance(payload["parameters"]["properties"], dict)
        # `job_output`'s wait is the one that matters to a model deciding whether
        # to spend a turn polling.
        if name == "job_output":
            assert "wait" in payload["parameters"]["properties"]
            assert "job_id" in payload["parameters"]["required"]


async def test_the_registry_is_empty_when_the_suite_starts():
    """Guards the autouse reset: a leaked job would make later counts wrong."""
    assert jobs_registry.all() == []


def test_a_job_needs_no_event_loop(host):
    """The registry is usable from plain synchronous code, which is why it is threads.

    `asyncio.subprocess.Process` would tie a job to the loop that created it, so a
    job could not outlive the turn that started it -- which is the one thing a
    background job is for. The proof is simply that this test is a `def` and not an
    `async def`: it starts, waits for and reads a real process with no loop running
    and no `await` anywhere.
    """
    job = jobs_registry.start(py("print('sync ok')"), host)
    wait_for(job)

    out, _, _, _ = job.read()
    assert "sync ok" in out
    assert job.returncode == 0
