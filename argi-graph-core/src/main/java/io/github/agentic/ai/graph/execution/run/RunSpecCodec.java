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

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.StreamReadFeature;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.MapperFeature;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.databind.json.JsonMapper;

/**
 * Strict data-only codecs, with no default typing, Java serialization or identity trust.
 */
public final class RunSpecCodec {

	private static final JsonMapper MAPPER = JsonMapper.builder()
		.enable(StreamReadFeature.STRICT_DUPLICATE_DETECTION)
		.disable(MapperFeature.ALLOW_COERCION_OF_SCALARS)
		.enable(MapperFeature.SORT_PROPERTIES_ALPHABETICALLY)
		.enable(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS)
		.enable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
		.enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS)
		.enable(DeserializationFeature.FAIL_ON_NULL_FOR_PRIMITIVES)
		.enable(DeserializationFeature.FAIL_ON_MISSING_CREATOR_PROPERTIES)
		.build();

	public String encodeRun(RunSpec spec) {
		return encode(spec);
	}

	public RunSpec decodeRun(String json) {
		return decode(json, RunSpec.class);
	}

	public String encodeTask(TaskSpec spec) {
		return encode(spec);
	}

	public TaskSpec decodeTask(String json) {
		return decode(json, TaskSpec.class);
	}

	private String encode(Object spec) {
		if (spec == null) {
			throw new IllegalArgumentException("spec cannot be null");
		}
		try {
			return MAPPER.writeValueAsString(spec);
		}
		catch (JsonProcessingException ex) {
			throw new IllegalArgumentException("Cannot encode execution spec", ex);
		}
	}

	private <T> T decode(String json, Class<T> type) {
		RunValidation.text(json, "json");
		try {
			T result = MAPPER.readValue(json, type);
			if (result == null) {
				throw new IllegalArgumentException("spec cannot be null");
			}
			return result;
		}
		catch (JsonProcessingException ex) {
			throw new IllegalArgumentException("Invalid execution spec", ex);
		}
	}

}
