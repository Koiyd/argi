# Copyright 2024-2026 the original author or authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

##@ Java

.PHONY: test
test: ## Run tests
	@$(LOG_TARGET)
	./mvnw test

# Separate build and test to speed up execution
.PHONY: build
build: ## Build the project
	@$(LOG_TARGET)
	./mvnw -B package --file pom.xml -DskipTests=true

.PHONY: dependency-audit
dependency-audit: ## Audit resolved runtime dependencies for high and critical advisories
	@$(LOG_TARGET)
	./mvnw -B -DskipTests=true package org.apache.maven.plugins:maven-dependency-plugin:3.9.0:tree -Dscope=runtime -DoutputType=json -DoutputFile=target/runtime-dependencies.json
	python3 -B tools/tests/runtime-dependency-audit-test.py
	python3 -B tools/scripts/audit-runtime-dependencies.py

.PHONY: sdk-boundaries-check
sdk-boundaries-check: ## Check production source, bytecode, and resolved SDK boundaries
	@$(LOG_TARGET)
	./mvnw -B -DskipTests=true package org.apache.maven.plugins:maven-dependency-plugin:3.9.0:tree -Dscope=runtime -DoutputType=json -DoutputFile=target/runtime-dependencies.json
	python3 -B tools/tests/sdk-boundaries-test.py
	python3 -B tools/scripts/check-sdk-boundaries.py

.PHONY: format-fix
format-fix: ## Format the code
	@$(LOG_TARGET)
	./mvnw spring-javaformat:apply

.PHONY: format-check
format-check: ## Format Check the code
	@$(LOG_TARGET)
	./mvnw spring-javaformat:validate

.PHONY: spotless-apply
spotless-apply: ## Run spotless and apply changes
	@$(LOG_TARGET)
	./mvnw spotless:apply

.PHONY: checkstyle-check
checkstyle-check: ## Checkstyle Check the code and output to target/checkstyle-report.xml
	@$(LOG_TARGET)
	./mvnw -Dcheckstyle.skip=false -Dcheckstyle.output.file=checkstyle-report.xml checkstyle:check

.PHONY: api-contract-check
api-contract-check: ## Compile current public API consumers without provider SDKs
	@$(LOG_TARGET)
	tools/scripts/verify-api-contract.sh
