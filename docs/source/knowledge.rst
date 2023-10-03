Knowledge
=========

Terminology
-----------

Image:
    Hardrive image, normally containing a functional operating
    system, and sometimes a service. It is identified with a pair 
    of strings in the form of ``name:tag`` (see below).

Image name: 
    First component in the user friendly ID of an image. Normally
    determines the service provided by the image, or the operating
    system stored. For instance ``ubuntu``, ``fedora``.

Image tag:
    Second component in the user friendly ID of an image. Normally
    determines the service version or flavour provided by the image; for generic
    images normally determines the version and or flavour. For instance 
    ``ubuntu:focal``, ``ubuntu:focal-desktop``.


Life cycle of a virtual machine
-------------------------------

The current model used by the library contemplates the
following stages in the life cycle of a virtual machine:

#. Inexistent
#. Building
#. Running
#. Sleep
#. Shutoff

There are pseudo-stages which exist only during a brief 
moment, normally between stages, which are irrelevant to
the user.

Inexistent
~~~~~~~~~~

This state represents any machine that does not exist,
either because ``spin up`` has not been called yet, or
because was completely destroyed.

Building
~~~~~~~~

State in which all the necessary information, files and
configuration is generated for the creation of the machine.
Depending on the definition, this may involve downloading
images, creating disk files, and finally contacting the
backend to register and start the machine.

Running
~~~~~~~

The immediate stage after the backend reporting success in 
the machine registration. The machine can be in any 
'internal' stage: booting, booted, powering off.

Sleep 
~~~~~

The machine has been freezed, with the internal state stored
in a file. The machine can be resumed, continuing exactly where
it left. For some applications this restoration can be confusing,
use with caution.

Shutoff
~~~~~~~

The machine is not running, and the start involves running the
entire boot process, independently of the power off method.