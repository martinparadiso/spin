Quickstart
==========


About this tool
---------------

This library/tool is highly inspired in 
`Vagrant <https://www.vagrantup.com/>`_, as can be observed
by the syntax and general structure. The main difference
between both libraries is that ``spin`` is written in Python
and it is completely unprofessional.

Apart from that, this library posses three main benefits:

- It is written as a library first, allowing to easily create
  images and machines using scripts that work directly on the 
  library API.
- Can build images directly without requiring a separate tool.
- Can leverage Python massive availability and ecosystem, to
  extend the functionality and ease integration.


Installation
------------

.. tip::

    **TL;DR**: Install with `pipx`:

    .. parsed-literal::
        pipx install 'spin[libvirt] @ \ |pip_url|\ '
        

    or manually, create a *virtualenv* to avoid problems, and 
    install with pip:

    .. parsed-literal:: shell
        
        python3 -m venv .env && source .env/bin/activate # Or activate.fish for fish shell
        pip install 'spin[libvirt] @\ |pip_url|\ '
        deactivate # Deactivate the environment since it's not necessary

        # Alias the python module to save on typing
        alias spin="$PWD/.env/bin/python -m spin"
    
    The rest of the document assumes you use the alias.

This tool is written in Python, and requires at least Python 
|min_python_version| and ``pip``. To install the library it
is recommended to use a *virtualenv*. This will keep the 
library and the dependencies inside this folder, without
affecting the rest of your Python installation:

.. literalinclude:: _static/examples/install_spin.sh
    :language: shell

To check if everything worked, check the ``spin`` version:

.. code-block:: shell

    python -m spin --version

Which will result in (probably): |version_output|. Also, it
will be handy to perform the following alias, to avoid typing 
``python -m`` every time:

.. code-block:: shell

    alias spin="$PWD/.env/bin/python -m spin"

You can now deactivate the *virtualenv* by calling:

.. code-block:: shell

    deactivate

The alias persists only in the current ``shell``, to install it
permanently you can create a file in ``~/.local/bin`` pointing to
the folder, something like:

.. code-block:: shell

    /<absolute-path-to-spin>/.env/bin/python -m spin $*

And making sure ``~/.local/bin`` is in your ``$PATH`` 
environment variable.


The basics of the command line tool
-----------------------------------

The command line interface (CLI) is a wrapper around the 
Python library, which provides facilities for managing 
machines without the need to write code.

To start a machine definition, create an empty directory
and run:

.. code-block:: shell

    spin init ubuntu:jammy

Which will create a file named ``spinfile``, following the 
conventions of other virtualization tools, containing only
the following:

.. code-block:: python
    
    # spinfile
    import spin

    with spin.define.vm('ubuntu', 'jammy') as vm:
        pass

To create and start the machine, run:

.. code-block:: shell

   spin up

A machine will be created in the default backend (currently 
`libvirt`), with all the missing details about the VM 
auto-filled. The reason this works is because ``ubuntu:jammy``
is a known image embedded into the library. Do not think the tool can
use any image in the form of ``distro:version``, the
tool has no infrastructure and all images are built locally.
The library supports, at the moment of writing, Ubuntu and MicroOS.

Starting the VM will create a ``.spin`` folder in
the same directory, containing metadata and files relevant
to the machine. Try not to remove this folder, if you do 
so, the library will contain a dangling reference to a
inexistent machine. 

Since the machine has no configuration, no SSH key has been inserted,
and Ubuntu has not configured the network. So for now we can only destroy it.

To *safely* destroy a machine, run:

.. code-block:: shell 

    spin destroy --storage

Customizing/provisioning the machine
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Once you call ``spin init``, or you manually create the ``spinfile``,
you can edit the characteristics of the machine using the following
attribute-based syntax:

.. literalinclude:: _static/examples/basic_characteristics.py
    :language: python
    

For a complete --and documented-- list of the properties, please
refer to :py:class:`~spin.machine.machine.Machine`. The most
common operations are described below.

.. danger::
    
    **Do not** store private keys, password, tokens or any kind 
    of credentials in the ``spinfile`` or shell script.


As of right now the easiest way to automatically *provision* 
a machine for development is to use the cloud-init plugin:

.. literalinclude:: _static/examples/cloud_init.py
   :language: python

The plugin will use ``cloud-init`` to provision the machine
with the default values, such as a default insecure key. Also,
the `cloud-init` service inside the machine will create users,
setup network, and perform all the necessary machine configurations
such as expanding the file system.

Connecting to the machine
~~~~~~~~~~~~~~~~~~~~~~~~~

To connect to a machine, the library provides a wrapper around
`ssh` to determine the target hostname and private key:

.. code-block:: shell

   spin ssh <machine name or UUID>

If you are standing in a directory containing a `.spin` folder,
you can SSH easily into the machine(s) defined there by using:

.. code-block:: shell

   spin ssh

You can pass commands to execute --and pipe stdin-- just like
a regular ssh command, to automatically determine the target
use `-` after ssh:

.. code-block:: shell

   # For instance to reboot the guest machine found in this
   # directory:
   spin ssh - sudo reboot


Running custom commands
^^^^^^^^^^^^^^^^^^^^^^^

To run arbitrary commands during the lifetime of the machine,
you can use the
:py:meth:`~spin.machine.machine.Machine.add_shell_script()` method.
The method takes a string containing commands to execute, and
a parameter indicating then the command should be run.

.. literalinclude:: _static/examples/shell_script.py
    :language: python
    

Notice the ``r`` before the Python multi-line string, this is
important if you include escape characters in the string. The
library takes this string, and generates a ``.sh`` file, which
will be passed to the machine to be executed. The string will
be splitted in lines, and the whitespaces trimmed. For the
multiline string in the previous example,  the generated
``.sh`` file is:

.. literalinclude:: _static/examples/shell_script.sh
    :language: shell
    

To generate dynamic commands, you can format the strings using
Python standard utilities, as shown in the third 
``add_shell_script()``.

.. note:: 

    The generated ``.sh`` files are stored in the ``.spin``
    folder. If the commands fails and you think the library
    is to blame, check the generated files for errors in
    the generation. Bug reports are always welcome, see 
    :ref:`reporting_bugs:Reporting bugs`.


Shared folders/volumes
^^^^^^^^^^^^^^^^^^^^^^

To share a folder between the host and guest, the following
syntax is used:

.. literalinclude:: _static/examples/shared_folders.py
    :language: python
    


Note that ``vm.shared_folders`` attribute is a list, allowing
for multiple shared folders between host and guest. Currently
there can be only one assignment, only the last assignment
will be registered.

.. note::

    Contrary to Vagrant, the folder where the ``spinfile``
    resides is not synced with the guest automatically.


