/*
 * Copyright 2025-2026 the original author or authors.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      https://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package io.github.agentic.ai.graph.execution.run;

import io.github.agentic.ai.graph.execution.ExecutionBudget;
import io.github.agentic.ai.graph.execution.TrustedExecutionContext;
import io.github.agentic.ai.graph.execution.TrustedExecutionContextReference;

import static java.util.Objects.requireNonNull;

/**
 * Recoverable run admission data. Graph id/version select application-registered code,
 * never serialized executable code. Deadline and budget live in the versioned context.
 */
public record RunSpec(int schemaVersion, RunNamespace namespace, String runId, String submissionKey, String inputHash,
		String graphId, String graphVersion, RunPayload input, TrustedExecutionContextReference context) {

	public static final int CURRENT_SCHEMA_VERSION = 1;

	public RunSpec {
		RunValidation.version(schemaVersion);
		requireNonNull(namespace, "namespace cannot be null");
		RunValidation.text(runId, "runId");
		RunValidation.text(submissionKey, "submissionKey");
		RunValidation.text(graphId, "graphId");
		RunValidation.text(graphVersion, "graphVersion");
		requireNonNull(input, "input cannot be null");
		RunValidation.context(context);
		if (!input.inputHash().equals(inputHash)) {
			throw new IllegalArgumentException("inputHash does not match the input");
		}
		if (!namespace.tenant().equals(context.tenant()) || !runId.equals(context.runId())) {
			throw new IllegalArgumentException("run identity does not match the context");
		}
	}

	public static RunSpec from(TrustedExecutionContext context, String applicationId, String sessionId,
			String submissionKey, String graphId, String graphVersion, RunPayload input) {
		return new RunSpec(CURRENT_SCHEMA_VERSION, RunNamespace.from(context, applicationId, sessionId),
				context.runId(), submissionKey, input.inputHash(), graphId, graphVersion, input, context.toReference());
	}

	public Long deadlineEpochMillis() {
		return context.deadlineEpochMillis();
	}

	public ExecutionBudget budget() {
		return new ExecutionBudget(context.budgetLimits());
	}
}
