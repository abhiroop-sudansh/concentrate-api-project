"""Safe parsing of /v1/responses JSON for output text and usage."""


def _text_from_content_list(content_list: list) -> list[str]:
    """Collect text from content items with type 'output_text' or 'text' and key 'text'."""
    parts: list[str] = []
    if not isinstance(content_list, list):
        return parts
    for c in content_list:
        if not isinstance(c, dict):
            continue
        if c.get("type") in ("output_text", "text") and "text" in c:
            t = c["text"]
            if isinstance(t, str):
                parts.append(t)
    return parts


def extract_output_text(resp_json: dict) -> str:
    """
    Extract the final output text from a /v1/responses response.

    Tries in order:
    1. Top-level "output_text" (string).
    2. Concatenated text from output[*]["content"][*] where type is "output_text" or "text" and "text" is present.
    3. choices[0].message.content (string or list of content parts with type/text).

    Never raises; returns "" if nothing found.
    """
    if not isinstance(resp_json, dict):
        return ""

    # 1. Top-level output_text
    output = resp_json.get("output_text")
    if output is not None and isinstance(output, str):
        return output

    # 2. output[*]["content"][*] — OpenAI /v1/responses-style
    output_list = resp_json.get("output")
    if isinstance(output_list, list):
        parts: list[str] = []
        for item in output_list:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            parts.extend(_text_from_content_list(content))
        if parts:
            return "".join(parts)

    # 3. choices[0].message.content — chat-completions style
    choices = resp_json.get("choices")
    if isinstance(choices, list) and len(choices) > 0:
        first = choices[0]
        if isinstance(first, dict):
            msg = first.get("message")
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    parts = _text_from_content_list(content)
                    if parts:
                        return "".join(parts)
                if content is None:
                    return ""

    return ""


def extract_usage(resp_json: dict) -> dict:
    """
    Extract usage info from a /v1/responses response.

    Returns a dict with keys such as total_tokens, prompt_tokens, completion_tokens.
    Returns {} if usage is missing or not a dict.
    """
    if not isinstance(resp_json, dict):
        return {}

    usage = resp_json.get("usage")
    if isinstance(usage, dict):
        return dict(usage)
    return {}
