DESCRIPTION = "Python bindings for the Apache Thrift RPC system"
HOMEPAGE = "https://pypi.python.org/pypi/thrift/"
SECTION = "devel/python"
LICENSE = "Apache-2.0"
LIC_FILES_CHKSUM = "file://PKG-INFO;md5=1203b6a05c3bff3229710e3f063ddca7"

SRCNAME = "thrift"

SRC_URI = "https://pypi.python.org/packages/source/t/${SRCNAME}/${SRCNAME}-${PV}.tar.gz;downloadfilename=${PN}-${PV}-python.tar.gz"

SRC_URI[md5sum] = "b519551d7a086bb0b4f222a8f566b7e8"
SRC_URI[sha256sum] = "dfbc3d3bd19d396718dab05abaf46d93ae8005e2df798ef02e32793cd963877e"

S = "${WORKDIR}/${SRCNAME}-${PV}"

inherit setuptools

BBCLASSEXTEND = "native"
