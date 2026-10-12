/*
 * Copyright 2024-2026 the original author or authors.
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
package io.github.agentic.ai.graph.utils;

import io.github.agentic.ai.api.chat.ChatMessage;

import org.springframework.util.StringUtils;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

public class Messageutils {

	private static final ObjectMapper objectMapper = new ObjectMapper();

	/**
	 * Generic method to convert various types of messages to message list Supported
	 * types: 1. String - converted to ChatMessage 2. Map (e.g. {"role": "user", "text":
	 * "test"}) - create corresponding ChatMessage based on role 3. Neutral ChatMessage -
	 * use directly 4. List - recursively process each element in the list
	 */
	public static List<ChatMessage> convertToMessages(Object value) {
		List<ChatMessage> result = new ArrayList<>();

		if (value == null) {
			return result;
		}

		if (value instanceof List<?>) {
			List<?> list = (List<?>) value;
			if (list.isEmpty()) {
				return result;
			}

			for (Object item : list) {
				result.addAll(convertToMessages(item));
			}
		}
		else if (value instanceof ChatMessage) {
			// Preserve an existing neutral message without rebuilding its content.
			result.add((ChatMessage) value);
		}
		else if (value instanceof String) {
			// If it's a string, convert to ChatMessage
			String text = (String) value;
			if (StringUtils.hasLength(text)) {
				result.add(ChatMessage.user(text));
			}
		}
		else if (value instanceof Map) {
			// If it's a Map, attempt to parse as ChatMessage
			Map<?, ?> map = (Map<?, ?>) value;
			ChatMessage message = convertMapToMessage(map);
			if (message != null) {
				result.add(message);
			}
		}
		else {
			// For other types, attempt conversion through JSON
			// serialization/deserialization
			try {
				String json = objectMapper.writeValueAsString(value);
				JsonNode jsonNode = objectMapper.readTree(json);
				if (jsonNode.isObject()) {
					ChatMessage message = convertJsonNodeToMessage(jsonNode);
					if (message != null) {
						result.add(message);
					}
				}
			}
			catch (Exception e) {
				// If conversion fails, treat it as a string
				String text = value.toString();
				if (StringUtils.hasLength(text)) {
					result.add(ChatMessage.user(text));
				}
			}
		}

		return result;
	}

	/**
	 * Convert Map to ChatMessage
	 */
	public static ChatMessage convertMapToMessage(Map<?, ?> map) {
		if (map == null || map.isEmpty()) {
			return null;
		}

		Object roleObj = map.get("role");
		Object textObj = map.get("text");
		Object contentObj = map.get("content");

		// Prioritize content, then text
		String content = null;
		if (contentObj != null) {
			content = contentObj.toString();
		}
		else if (textObj != null) {
			content = textObj.toString();
		}

		if (!StringUtils.hasLength(content)) {
			return null;
		}

		String role = roleObj != null ? roleObj.toString().toLowerCase() : "user";

		switch (role) {
			case "system":
				return ChatMessage.system(content);
			case "assistant":
				return ChatMessage.assistant(content);
			case "user":
			default:
				return ChatMessage.user(content);
		}
	}

	/**
	 * Convert JsonNode to ChatMessage
	 */
	public static ChatMessage convertJsonNodeToMessage(JsonNode jsonNode) {
		if (jsonNode == null || !jsonNode.isObject()) {
			return null;
		}

		JsonNode roleNode = jsonNode.get("role");
		JsonNode textNode = jsonNode.get("text");
		JsonNode contentNode = jsonNode.get("content");

		// Prioritize content, then text
		String content = null;
		if (contentNode != null && contentNode.isTextual()) {
			content = contentNode.asText();
		}
		else if (textNode != null && textNode.isTextual()) {
			content = textNode.asText();
		}

		if (!StringUtils.hasLength(content)) {
			return null;
		}

		String role = roleNode != null && roleNode.isTextual() ? roleNode.asText().toLowerCase() : "user";

		return switch (role) {
			case "system" -> ChatMessage.system(content);
			case "assistant" -> ChatMessage.assistant(content);
			case "user" -> ChatMessage.user(content);
			default -> ChatMessage.user(content);
		};
	}

}
