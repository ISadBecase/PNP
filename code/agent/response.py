import json_repair


def get_json_from_response(raw_response):
    response = raw_response.strip()
    left = response.rfind("```json")
    right = response.rfind("```")

    try:
        if left == -1 or right <= left:
            result = json_repair.loads(response)
        else:
            result = json_repair.loads(response[left + 7:right].strip())
        if not isinstance(result, (dict, list)):
            raise ValueError("The response is not a JSON object or array")
        return result
    except Exception as error:
        raise RuntimeError("Failed to parse JSON from response") from error
