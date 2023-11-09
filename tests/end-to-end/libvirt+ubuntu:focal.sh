#!/bin/bash

# Print the current time and a message
stage()  {
    echo "[$(date --iso=seconds)]" "***" $@ "***" 
}

usage() {
cat << EOF
Usage: --home <HOME> --make-pool <true|false>

  --home        specifies the folder to create .config/ and .local/ 
  --make-pool   specifies whether the libvirt 'default' pool should
                be created or is already present.
EOF
}


opts=$(getopt --options '' --longoptions 'home:,make-pool:' -- "$@")

declare TEST_HOME MAKE_POOL
eval set -- "$opts"
while (($#))
do
  case $1 in
    --home)           
      TEST_HOME=$2; shift;;
    --make-pool)
      case "$2" in
        true)   MAKE_POOL=1; shift;;
        false)  MAKE_POOL=0; shift;;
        *)      echo '--make-pool accepts only true or false'; exit 1;;
      esac
      ;;
  esac
  shift
done
set -e

if [ -z "$MAKE_POOL" ]; then
  echo 'Missing --make-pool' && exit 1
fi

if [ -z "$TEST_HOME" ]; then
  echo 'Missing --home' && exit 1
fi

export XDG_CONFIG_HOME="$TEST_HOME"/.config
export XDG_DATA_HOME="$TEST_HOME"/.local/share

stage 'Printing host information for debugging'
uname --all       # For the kernel version
cat /proc/cpuinfo # CPU capabilities and version
# sudo kvm-ok       # KVM configuration
python --version  # Python version
virsh --version   # Virsh version

stage 'Creating virtual-env and installing dependencies'
python -m venv .env
source .env/bin/activate
pip install -U pip
pip install .[libvirt]

stage 'Creating necessary user folders'
mkdir --parents --mode=700 "$TEST_HOME"/.local/state "$TEST_HOME"/.local/share "$TEST_HOME"/.config

if [ "$MAKE_POOL" == "1" ]; then
  stage 'Creating libvirt pool'
  virsh -c qemu:///system pool-define-as --name default \
    --type dir \
    --target /var/lib/libvirt/images/
  virsh -c qemu:///system pool-autostart default
  virsh -c qemu:///system pool-start default
else
  stage 'Skipping libvirt pool creation'
fi

stage 'Initializing config and image definition database'
spin -vvv init-conf
spin -vvv update-database --init

stage 'Call spin init and spin up'
spin -vvv init ubuntu:focal --memory=1GiB --plugin=spin.plugin.cloud_init
spin -vvv up --console

stage 'Running tests from shell'
test $(virsh -c qemu:///system list | grep spin | wc -l) -eq 1
MACHINE_NAME=$(virsh -c qemu:///system list --name | grep spin)
virsh -c qemu:///system dumpxml "$MACHINE_NAME"

stage 'Calling spin down'
spin -vvv down
test $(virsh -c qemu:///system list | grep "$MACHINE_NAME" | wc -l) -eq 0
test $(virsh -c qemu:///system list --all | grep "$MACHINE_NAME" | wc -l) -eq 1

stage 'Calling spin destroy'
spin -vvv destroy --storage
test $(virsh -c qemu:///system list | grep "$MACHINE_NAME" | wc -l) -eq 0
test $(virsh -c qemu:///system list --all | grep "$MACHINE_NAME" | wc -l) -eq 0
