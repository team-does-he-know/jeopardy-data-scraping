from json import dumps, loads
from urllib.request import Request, urlopen

# LM Studio OpenAI-compatible chat completions endpoint and configuration.
LM_STUDIO_API_URL = (
    # SUN Lab Cray's local network IP. Usually, you'll want to just use `localhost`.
    # But I am running this through a microVM. So, I need to workaround some networking
    # restrictions.
    "http://10.162.14.155:1234/v1/chat/completions"
)

LM_STUDIO_MODEL_IDENTIFIER = "google/gemma-4-26b-a4b-qat"


def request_chat_completion(
    system_prompt,
    user_prompt,
    response_schema=None,
    temperature=None,
    seed=None,
    presence_penalty=None,
    frequency_penalty=None,
    timeout=None,
):
    """Sends a chat completion request to the local LLM server and returns parsed JSON."""
    payload = {
        "model": LM_STUDIO_MODEL_IDENTIFIER,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    if response_schema is not None:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": response_schema,
        }

    if temperature is not None:
        payload["temperature"] = temperature

    if seed is not None:
        payload["seed"] = seed

    if presence_penalty is not None:
        payload["presence_penalty"] = presence_penalty

    if frequency_penalty is not None:
        payload["frequency_penalty"] = frequency_penalty

    request = Request(
        LM_STUDIO_API_URL,
        data=dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    urlopen_kwargs = {}

    if timeout is not None:
        urlopen_kwargs["timeout"] = timeout

    with urlopen(request, **urlopen_kwargs) as response:
        response_data = loads(response.read().decode("utf-8"))

    raw_content = response_data["choices"][0]["message"]["content"]

    return loads(raw_content)
