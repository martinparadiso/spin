.. spin documentation master file, created by
   sphinx-quickstart on Thu Sep 15 23:49:05 2022.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Welcome to spin's documentation!
================================

``spin`` is a virtual machine manager, with support for image and machine
definition, with a backend-agnostic interface.

Brief summary
-------------

The simplest machine definition looks like this:

.. code-block:: python

    # spinfile
    import spin

    with spin.define.vm('ubuntu', 'jammy') as vm:
        pass

and the command for starting the machine, called from the directory containing
the previous ``spinfile``:

.. code-block:: shell

    spin up

This will create a virtual machine, using the default backend [#def_backend]_, 
running the standard Ubuntu Jammy image. All missing information is auto 
completed by the library, for instance the disk will have ``10GiB`` of capacity,
and the network card will connect to an isolated virtual network, with NAT 
forwarding.

.. rubric:: Footnotes

.. [#def_backend] The default backend depends on the binaries found by the
   library. Currently only `libvirt` is supported.

.. warning::
    The library is **highly** experimental and, in essence, a `pet-project`, use
    with caution.

.. toctree::
   :maxdepth: 1
   :caption: Contents:
   :glob:

   quickstart
   image_building
   knowledge
   modules
   reporting_bugs


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
