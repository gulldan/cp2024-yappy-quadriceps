PROTOC_VERSION = 24.3
PROTOC_RELEASES = https://github.com/protocolbuffers/protobuf/releases
SWAGGER_VERSION = 0.30.5
SWAGGER_RELEASES = https://github.com/go-swagger/go-swagger/releases

TOOLS_BIN_DIR = ${PWD}/tools/bin
PROTO_DIR = ${PWD}/proto
PROTO_DIR_BFF = $(PROTO_DIR)/bff/v1

install-protoc:
	@if [ ! -f $(TOOLS_BIN_DIR)/protoc ]; then \
		cd tools && \
		curl -LO $(PROTOC_RELEASES)/download/v$(PROTOC_VERSION)/protoc-$(PROTOC_VERSION)-linux-x86_64.zip && \
		unzip protoc-$(PROTOC_VERSION)-linux-x86_64.zip -d $(TOOLS_BIN_DIR) && \
		mv $(TOOLS_BIN_DIR)/bin/protoc $(TOOLS_BIN_DIR) && \
		rm -rf $(TOOLS_BIN_DIR)/bin $(TOOLS_BIN_DIR)/readme.txt && \
		rm protoc-$(PROTOC_VERSION)-linux-x86_64.zip; \
	fi

install-swagger:
	@if [ ! -f $(TOOLS_BIN_DIR)/swagger ]; then \
		cd tools && \
		curl -LO $(SWAGGER_RELEASES)/download/v$(SWAGGER_VERSION)/swagger_linux_amd64 && \
		mv swagger_linux_amd64 $(TOOLS_BIN_DIR)/swagger && \
		chmod +x $(TOOLS_BIN_DIR)/swagger; \
	fi

install-go-tools:
	@cd tools && \
	GOBIN=$(TOOLS_BIN_DIR) go install \
	github.com/grpc-ecosystem/grpc-gateway/v2/protoc-gen-grpc-gateway \
	github.com/grpc-ecosystem/grpc-gateway/v2/protoc-gen-openapiv2 \
	google.golang.org/protobuf/cmd/protoc-gen-go \
	google.golang.org/grpc/cmd/protoc-gen-go-grpc \
	go.uber.org/mock/mockgen \
	github.com/bufbuild/buf/cmd/protoc-gen-buf-lint \
  github.com/oapi-codegen/oapi-codegen/v2/cmd/oapi-codegen

install-tools: install-protoc install-swagger install-go-tools

clear-proto:
	rm -rf \
		$(PROTO_DIR_BFF)/*pb.gw.go \
		$(PROTO_DIR_BFF)/*.pb.go \
		$(PROTO_DIR_BFF)/*.swagger.json

generate-proto: install-tools clear-proto
	$(TOOLS_BIN_DIR)/protoc -I . \
		--plugin=protoc-gen-go=$(TOOLS_BIN_DIR)/protoc-gen-go \
		--plugin=protoc-gen-grpc-gateway=$(TOOLS_BIN_DIR)/protoc-gen-grpc-gateway \
		--plugin=protoc-gen-openapiv2=$(TOOLS_BIN_DIR)/protoc-gen-openapiv2 \
		--plugin=protoc-gen-go-grpc=$(TOOLS_BIN_DIR)/protoc-gen-go-grpc \
		-I $(PROTO_DIR) \
		--go_out $(PROTO_DIR) --go_opt paths=source_relative \
		--go-grpc_out $(PROTO_DIR) --go-grpc_opt paths=source_relative \
		--grpc-gateway_out $(PROTO_DIR) \
		--grpc-gateway_opt logtostderr=true \
		--grpc-gateway_opt paths=source_relative \
		--grpc-gateway_opt generate_unbound_methods=true \
		--openapiv2_out . \
		--openapiv2_opt logtostderr=true,allow_merge=true,merge_file_name=bff \
		--proto_path=$(PROTO_DIR_BFF) \
			$(PROTO_DIR_BFF)/bff.proto
	cp bff.swagger.json ./swagger-ui/docs


generate-client: install-tools
	swagger generate server -f ./docs/swagger.yaml

generate: install-tools generate-proto generate-client

test:
	go test -v ./...

lint: install-tools 
	@$(TOOLS_BIN_DIR)/protoc \
		--plugin=protoc-gen-buf-lint=$(TOOLS_BIN_DIR)/protoc-gen-buf-lint \
		--buf-lint_out=$(PROTO_DIR) \
		--buf-lint_opt='{"input_config":{"version":"v1beta1","lint":{"allow_comment_ignores":true,"ignore":["grpc"]}}}' \
		-I $(PROTO_DIR) \
		--proto_path=$(PROTO_DIR_BFF) \
		$(PROTO_DIR_BFF)/*.proto
	@golangci-lint run ./...
