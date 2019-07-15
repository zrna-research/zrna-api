PROTOC = protoc
NANOPB_DIR := external/nanopb-master
PB_DEF_DIR := proto
PYTHON_API_CLIENT_DIR := python-api-client

PROTOC_OPTS = --plugin=protoc-gen-nanopb=$(NANOPB_DIR)/generator/protoc-gen-nanopb
PROTO_SOURCES := $(shell find $(PB_DEF_DIR) -type f -name *.proto)

PROTO_PYTHON_OUT = proto/python
PROTO_CPP_OUT = proto/cpp
PROTO_JAVA_OUT = proto/java
PROTO_JS_OUT = proto/js
PROTO_GOLANG_OUT = proto/golang
PROTO_NANOPB_OUT = proto/nanopb
PROTO_OUTPUT_DIRS = $(PROTO_PYTHON_OUT) $(PROTO_CPP_OUT) $(PROTO_JAVA_OUT) \
	$(PROTO_JS_OUT) $(PROTO_GOLANG_OUT) $(PROTO_NANOPB_OUT)

all: $(PB_DEF_DIR)/zr.proto | output_directories
	$(PROTOC) -I$(PB_DEF_DIR) $(PROTOC_OPTS) '--nanopb_out=-I$(PB_DEF_DIR) -v:$(PROTO_NANOPB_OUT)' \
	--python_out=$(PROTO_PYTHON_OUT) \
	--cpp_out=$(PROTO_CPP_OUT) \
	--java_out=$(PROTO_JAVA_OUT) \
	--js_out=$(PROTO_JS_OUT) \
	--go_out=$(PROTO_GOLANG_OUT) $<
	sed -i -E 's/^import.*_pb2/from . \0/' $(PROTO_PYTHON_OUT)/*.py
	cp $(PROTO_PYTHON_OUT)/zr_pb2.py $(PYTHON_API_CLIENT_DIR)

output_directories:
	for output_directory in $(PROTO_OUTPUT_DIRS) ; do \
		mkdir -p $$output_directory ; \
    done

clean:
	for output_directory in $(PROTO_OUTPUT_DIRS) ; do \
		rm -f ./$$output_directory/* ; \
    done

.PHONY: clean
.PHONY: all
