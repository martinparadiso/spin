# Create a new machine; running Ubuntu Jammy,
# auto-generate cloud_init data source using the built-in
# plugin.

set -e

# Create a new spinfilfocale.py in this directory
spin init ubuntu:focal --plugin=spin.plugin.cloud_init

# Create and start the machine
spin up

# SSH into it; and print the hostname
spin ssh - hostname
#        │
#        ╰─ this indicates auto destination detection;
#           useful when you want to send commands without
#           typing the machine name.

# Stop it
spin down

# And destroy it, with all storage
spin destroy --storage
