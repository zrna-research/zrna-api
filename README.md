# zrna - software-defined analog
Protobuf definition and API clients for the Zrna software-defined analog platform.

See [zrna.org/docs](https://zrna.org/docs) for the full documentation.

Order [hardware](https://zrna.org/shop).

## The Protobuf Spec
The `proto` directory contains the protobuf definition and also serves
as the root output directory for generated sources.  Issuing `make` from
the root directory will compile everything and generate code with the `protoc`
compiler. The assumption is that `protoc` is available on your `PATH` and also
that Golang source generation is available (this requires setup beyond the default
`protoc` installation. See [https://github.com/golang/protobuf](https://github.com/golang/protobuf).
If you are interested in particular languages, simply disable the ones you don't need in the
`Makefile`.

By default, the build process generates bindings for Python, C++, Java, JavaScript, Golang
and plain C via Nanopb. The generated sources for each of these end up in the following
directories:
```
proto/python
proto/cpp
proto/java
proto/js
proto/golang
proto/nanopb
```
Zrna hardware uses the nanopb binding natively which is usually the best choice for constrained embedded
environments. As is normally the case with protobuf though,
a common binary wire format is generated regardless of what language binding is used, i.e. your
client is free to use any of the language bindings. If this is your first time working with protobuf, it's worth it to review the docs: [https://developers.google.com/protocol-buffers/](https://developers.google.com/protocol-buffers/).

## The Python Client
The `zrna` directory contains the sources for the Python API client that is available on PyPI as `zrna`. It's built on the Python bindings generated in the previous step. See the [quickstart guide](https://zrna.org/docs/quickstart) for more information about how to use it. See the [demo applications](https://zrna.org/demos) for usage examples.
