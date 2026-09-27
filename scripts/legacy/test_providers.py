from tonyagent.providers import provider_registry, ProviderFactory

print('Providers:', provider_registry.list_providers())
print('Factory available:', len(ProviderFactory.get_available_providers()))
for p in ProviderFactory.get_available_providers():
    print(f"  {p['name']}: {p['models']} (has_key={p['has_credentials']})")