targetScope = 'subscription'

// Each run gets a fresh group. Challenge resources and assignments belong in it,
// not in the rest of the sandbox subscription.
resource lab 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${deployment().name}'
  location: deployment().location
  tags: {
    lab: 'sovereign-governance-microhack'
    run: deployment().name
  }
}

output resourceGroupName string = lab.name
