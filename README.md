# Spin — An underperforming VM manager

**WARNING**: experimental project, use (or better, don't) at your own
risk.

## Documentation

Please refer to the main documentation for additional
information, available at: <https://martinparadiso.github.io/spin>

## Installing

The library relies on the following non-pip dependencies, for `ubuntu` 
the packages are:

```
build-essential netcat genisoimage qemu-kvm cpu-checker libvirt-daemon-system
python-is-python3 python3-pip python3-dev python3-venv libc-dev pkg-config
dnsmasq libguestfs-tools libguestfs-dev libvirt-dev
```

The package is split in optional dependencies, so you install only
the backend you use, for `libvirt` (the only currently implemented)
the command is:

```shell
pipx install 'spin[libvirt] @ https://github.com/martinparadiso/spin.git'
```
`pipx` is the recommended way of installing, if you want to install it
manually please use a virtual environment:

```shell
mkdir spin && cd spin
python -m venv .env && source .env/bin/activate
pip install 'spin[libvirt] @ https://github.com/martinparadiso/spin.git'
```

Note that you will need to resource the environment every time you
want to use `spin`. (Or `.env/bin` to your `$PATH`).

## Development

Install using ``poetry``:

```shell
git clone https://github.com/martinparadiso/spin
poetry install --with docs,tests --extras=libvirt
```
