from flask import Flask, request, jsonify
import requests
import json
import time
import os
import re  # Import the 're' module

app = Flask(__name__)

# Restructured MODEL_URLS to separate submit and status/result URLs
MODEL_URLS = {
    "flux-1.1-ultra": {
        "submit_url": "https://queue.fal.run/fal-ai/flux-pro/v1.1-ultra",
        "status_base_url": "https://queue.fal.run/fal-ai/flux-pro"
    },
    "recraft-v3": {
        "submit_url": "https://queue.fal.run/fal-ai/recraft-v3",
        "status_base_url": "https://queue.fal.run/fal-ai/recraft-v3"
    },
    "flux-1.1-pro": {
        "submit_url": "https://queue.fal.run/fal-ai/flux-pro/v1.1",
        "status_base_url": "https://queue.fal.run/fal-ai/flux-pro"
    },
    "ideogram-v2": {
        "submit_url": "https://queue.fal.run/fal-ai/ideogram/v2",
        "status_base_url": "https://queue.fal.run/fal-ai/ideogram"
    },
    "dall-e-3": {
        "submit_url": "https://queue.fal.run/fal-ai/flux/dev",
        "status_base_url": "https://queue.fal.run/fal-ai/flux"
    }
}

# REMOVED: The extract_image_request function is removed.

@app.route('/v1/chat/completions', methods=['POST'])
def chat_completions():
    """
    Handles chat completions requests, routing to different Fal models.
    """
    auth_header = request.headers.get('Authorization', '')
    print(f"Received Authorization header: {auth_header}")

    if auth_header.startswith('Bearer '):
        api_key = auth_header[7:]
    elif auth_header.startswith('Key '):
        api_key = auth_header[4:]
    else:
        api_key = auth_header

    print(f"Extracted API key: {api_key[:5]}...{api_key[-5:] if len(api_key) > 10 else ''}")

    if not api_key:
        print("No API key provided")
        return jsonify({
            "error": {
                "message": "Missing API key. Provide it in the Authorization header.",
                "type": "authentication_error"
            }
        }), 401

    openai_request = request.json
    if not openai_request:
        return jsonify({
            "error": {
                "message": "Missing or invalid request body",
                "type": "invalid_request_error"
            }
        }), 400

    messages = openai_request.get('messages', [])
    model = openai_request.get('model', 'dall-e-3')  # Default

    # DIRECTLY USE THE LAST USER MESSAGE AS THE PROMPT
    prompt = ""
    last_user_message = next((msg['content'] for msg in reversed(messages) if msg.get('role') == 'user'), None)
    if last_user_message:
      prompt = last_user_message

    if not prompt:
        completions_response = {
            "id": f"chatcmpl-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "I can generate images. Describe what you'd like."
                    },
                    "finish_reason": "stop"
                }
            ],
            "usage": {
                "prompt_tokens": len(json.dumps(messages)) // 4,
                "completion_tokens": 20,
                "total_tokens": (len(json.dumps(messages)) // 4) + 20
            }
        }
        return jsonify(completions_response)

    print(f"Extracted image prompt: {prompt}")
    n = 1
    fal_request = {"prompt": prompt, "num_images": n}
    print("Making request to Fal API...")

    # Get the correct URLs based on the model
    fal_submit_url = MODEL_URLS.get(model, MODEL_URLS["dall-e-3"])["submit_url"]
    fal_status_base_url = MODEL_URLS.get(model, MODEL_URLS["dall-e-3"])["status_base_url"]
    print(f"Using model: {model}, Submit URL: {fal_submit_url}, Status Base URL: {fal_status_base_url}")

    try:
        headers = {"Authorization": f"Key {api_key}", "Content-Type": "application/json"}

        print(f"Headers: Authorization: Key {api_key[:5]}...{api_key[-5:] if len(api_key) > 10 else ''}")
        print(f"Request URL: {fal_submit_url}")
        print(f"Payload: {json.dumps(fal_request)}")

        fal_response = requests.post(fal_submit_url, headers=headers, json=fal_request)

        print(f"Fal API response status: {fal_response.status_code}")
        print(f"Fal API response: {fal_response.text[:200]}...")

        if fal_response.status_code != 200:
            try:
                error_data = fal_response.json()
                error_message = error_data.get('error', {}).get('message', fal_response.text)
            except:
                error_message = fal_response.text

            print(f"Fal API error: {fal_response.status_code}, {error_message}")

            if fal_response.status_code in (401, 403):
                return jsonify({
                    "error": {
                        "message": f"Authentication error with Fal API: {error_message}",
                        "type": "invalid_api_key",
                        "code": fal_response.status_code
                    }
                }), 401

            return jsonify({
                "error": {
                    "message": f"Fal API error: {error_message}",
                    "type": "fal_api_error",
                    "code": fal_response.status_code
                }
            }), 500

        fal_data = fal_response.json()
        request_id = fal_data.get("request_id")
        if not request_id:
            print("No request_id found in Fal response.")
            return jsonify({"error": {"message": "Missing request_id", "type": "fal_api_error"}}), 500

        print(f"Got request_id: {request_id}")

        image_urls = []
        max_attempts = 60
        for attempt in range(max_attempts):
            print(f"Polling attempt {attempt+1}/{max_attempts}")
            try:
                # Construct the correct status and result URLs
                status_url = f"{fal_status_base_url}/requests/{request_id}/status"
                result_url = f"{fal_status_base_url}/requests/{request_id}"

                print(f"Checking status URL: {status_url}")
                status_headers = {
                    "Authorization": f"Key {api_key}",
                    "Content-Type": "application/json"  # Include Content-Type
                }
                status_response = requests.get(status_url, headers=status_headers)
                print(f"Status response code: {status_response.status_code}")

                if status_response.status_code == 200:
                    status_data = status_response.json()
                    status = status_data.get("status")
                    print(f"Current status: {status}")

                    if status == "FAILED":
                        print("Generation failed!")
                        return jsonify({"error": {"message": "Image generation failed", "type": "generation_failed"}}), 500

                    if status == "COMPLETED":
                        print(f"Fetching result from: {result_url}")
                        result_response = requests.get(result_url, headers={"Authorization": f"Key {api_key}"}) # Content-type not needed for result
                        print(f"Result fetch status: {result_response.status_code}")

                        if result_response.status_code == 200:
                            result_data = result_response.json()
                            print(f"Result data preview: {str(result_data)[:200]}...")

                            if "images" in result_data:
                                images = result_data.get("images", [])
                                for img in images:
                                    if isinstance(img, dict) and "url" in img:
                                        image_urls.append(img.get("url"))
                                        print(f"Found image URL: {img.get('url')}")

                            if image_urls:
                                break
                            else:
                                print("Completed, no images found.")

                    time.sleep(2)
                else:
                    print(f"Error checking status: {status_response.text}")
                    time.sleep(2)

            except Exception as e:
                print(f"Error during polling: {str(e)}")
                time.sleep(2)

        if not image_urls:
            print("No images found after polling.")
            completions_response = {
                "id": f"chatcmpl-{request_id}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "Unable to generate an image. Try a different description."
                        },
                        "finish_reason": "stop"
                    }
                ],
                "usage": {
                    "prompt_tokens": len(prompt) // 4,
                    "completion_tokens": 30,
                    "total_tokens": (len(prompt) // 4) + 30
                }
            }
            return jsonify(completions_response)

        content = f"Here's the image: \"{prompt}\"\n\n"
        for i, url in enumerate(image_urls):
            if i > 0:
                content += "\n\n"
            content += f"![Generated Image {i+1}]({url})"

        completions_response = {
            "id": f"chatcmpl-{request_id}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": content
                    },
                    "finish_reason": "stop"
                }
            ],
            "usage": {
                "prompt_tokens": len(prompt) // 4,
                "completion_tokens": len(content) // 4,
                "total_tokens": (len(prompt) // 4) + (len(content) // 4)
            }
        }

        print(f"Returning OpenAI completions-style response")
        return jsonify(completions_response)

    except Exception as e:
        print(f"Exception: {str(e)}")
        return jsonify({"error": {"message": f"Server error: {str(e)}", "type": "server_error"}}), 500


@app.route('/v1/images/generations', methods=['POST'])
def generate_image():
    """Legacy endpoint for direct image generations."""
    auth_header = request.headers.get('Authorization', '')

    if auth_header.startswith('Bearer '):
        api_key = auth_header[7:]
    elif auth_header.startswith('Key '):
        api_key = auth_header[4:]
    else:
        api_key = auth_header

    if not api_key:
        return jsonify({"error": {"message": "Missing API key.", "type": "authentication_error"}}), 401

    openai_request = request.json
    if not openai_request:
        return jsonify({"error": {"message": "Missing or invalid request body", "type": "invalid_request_error"}}), 400

    prompt = openai_request.get('prompt', '')
    n = openai_request.get('n', 1)
    model = openai_request.get('model', 'dall-e-3')

    chat_request = {"model": model, "messages": [{"role": "user", "content": prompt}]}
    request.json = chat_request
    return chat_completions()

@app.route('/v1/models', methods=['GET'])
def list_models():
    """Mock OpenAI models endpoint."""
    models = [
        {"id": "dall-e-3", "object": "model", "created": 1698785189, "owned_by": "fal-openai-adapter", "permission": [], "root": "dall-e-3", "parent": None},
        {"id": "gpt-4-vision-preview", "object": "model", "created": 1698785189, "owned_by": "fal-openai-adapter", "permission": [], "root": "gpt-4-vision-preview", "parent": None},
        {"id": "flux-1.1-ultra", "object": "model", "created": 1698785189, "owned_by": "fal-openai-adapter", "permission": [], "root": "flux-1.1-ultra", "parent": None},
        {"id": "recraft-v3", "object": "model", "created": 1698785189, "owned_by": "fal-openai-adapter", "permission": [], "root": "recraft-v3", "parent": None},
        {"id": "flux-1.1-pro", "object": "model", "created": 1698785189, "owned_by": "fal-openai-adapter", "permission": [], "root": "flux-1.1-pro", "parent": None},
        {"id": "ideogram-v2", "object": "model", "created": 1698785189, "owned_by": "fal-openai-adapter", "permission": [], "root": "ideogram-v2", "parent": None}
    ]
    return jsonify({"object": "list", "data": models})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5005))
    print(f"Starting server on port {port}...")
    app.run(host='0.0.0.0', port=port, debug=True)
