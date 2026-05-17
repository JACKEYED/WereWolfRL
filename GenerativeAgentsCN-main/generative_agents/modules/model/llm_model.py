# 文件作用：封装 OpenAI 兼容接口和 Ollama 接口，提供统一的大模型 completion 调用。

import time
import re
import requests
import json


class LLMModel:
    def __init__(self, config):
        self._api_key = config["api_key"]
        self._base_url = config["base_url"]
        self._model = config["model"]
        self._summary = {"total": [0, 0, 0]}

        self._handle = self.setup(config)
        self._enabled = True
        # 最近一次 _completion 调用的原始数据。RL trainer 通过 director._last_capture 提取。
        # 字段：{"prompt": str, "text": str, "logprobs": List[float]|None, "tokens": List[str]|None}
        self.last_call = None

    def setup(self, config):
        raise NotImplementedError(
            "setup is not support for " + str(self.__class__)
        )

    def completion(
        self,
        prompt,
        retry=10,
        callback=None,
        failsafe=None,
        return_type=None,
        caller="llm_normal",
        **kwargs
    ):
        response = None
        self._summary.setdefault(caller, [0, 0, 0])
        for _ in range(retry):
            try:
                output = self._completion(prompt, return_type, **kwargs)
                self._summary["total"][0] += 1
                self._summary[caller][0] += 1
                if callback:
                    response = callback(output)
                else:
                    response = output
            except Exception as e:
                print(f"LLMModel.completion() caused an error: {e}")
                time.sleep(5)
                response = None
                continue
            if response is not None:
                break
        pos = 2 if response is None else 1
        self._summary["total"][pos] += 1
        self._summary[caller][pos] += 1
        return response or failsafe

    def _completion(self, prompt, return_type, **kwargs):
        raise NotImplementedError(
            "_completion is not support for " + str(self.__class__)
        )

    def is_available(self):
        return self._enabled  # and self._summary["total"][2] <= 10

    def get_summary(self):
        des = {}
        for k, v in self._summary.items():
            des[k] = "S:{},F:{}/R:{}".format(v[1], v[2], v[0])
        return {"model": self._model, "summary": des}

    def disable(self):
        self._enabled = False


class OpenAILLMModel(LLMModel):
    def setup(self, config):
        from openai import OpenAI

        return OpenAI(api_key=self._api_key, base_url=self._base_url)

    def _completion(self, _prompt, return_type, temperature=0.5):
        response = self._handle.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": _prompt}],
            temperature=temperature,
        )
        raw = response.choices[0].message.content or ""
        # 记录原始调用（不含 logprob，因为 OpenAI / DeepSeek 大多不返回）
        self.last_call = {"prompt": _prompt, "text": raw, "logprobs": None, "tokens": None}
        return _parse_json_response(raw, return_type)


class VLLMLocalModel(LLMModel):
    """走本地 vLLM 服务（OpenAI 兼容协议），额外抓 token-level logprob 用于 RL 训练。
    部署：vllm serve <qwen_model_dir> --host 127.0.0.1 --port 8001
    config 示例：
      provider: vllm
      model: Qwen/Qwen2.5-7B-Instruct
      base_url: http://127.0.0.1:8001/v1
      api_key: EMPTY
    """

    def setup(self, config):
        from openai import OpenAI

        return OpenAI(api_key=self._api_key or "EMPTY", base_url=self._base_url)

    def _completion(self, _prompt, return_type, temperature=0.5):
        response = self._handle.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": _prompt}],
            temperature=temperature,
            logprobs=True,
            top_logprobs=1,
            extra_body=self._guided_json_extra(return_type),
        )
        choice = response.choices[0]
        raw = choice.message.content or ""
        logprobs, tokens = self._extract_logprobs(choice)
        self.last_call = {
            "prompt": _prompt,
            "text": raw,
            "logprobs": logprobs,
            "tokens": tokens,
        }
        return _parse_json_response(raw, return_type)

    @staticmethod
    def _guided_json_extra(return_type):
        """对 pydantic return_type，让 vLLM 用 guided JSON 强约束输出格式。"""
        if return_type is None:
            return None
        try:
            return {"guided_json": return_type.model_json_schema()}
        except Exception:
            return None

    @staticmethod
    def _extract_logprobs(choice):
        """从 OpenAI 风格 choice.logprobs.content 抽 token 级 logprob 与 token 字符串。"""
        try:
            content = choice.logprobs.content or []
        except AttributeError:
            return None, None
        logprobs = [getattr(t, "logprob", None) for t in content]
        tokens = [getattr(t, "token", "") for t in content]
        # 任何 None 即视为不可用
        if any(lp is None for lp in logprobs):
            return None, None
        return logprobs, tokens


def _parse_json_response(raw: str, return_type):
    """OpenAI / vLLM 共用的 JSON 响应解析：剥 <think>，按 pydantic 模型校验。
    若 pydantic 模型有 `.res` 字段（TextResponse/ChoiceResponse 约定）则取 .res；
    否则返回整个模型实例（供 JudgeResponse 等多字段模型用，由 callback 自取字段）。
    """
    output = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    if return_type is None:
        return output
    try:
        parsed = json.loads(output)
        obj = return_type.model_validate(parsed)
        return obj.res if hasattr(obj, "res") else obj
    except json.JSONDecodeError:
        json_match = re.search(r"\{.*\}", output, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group())
            obj = return_type.model_validate(parsed)
            return obj.res if hasattr(obj, "res") else obj
        return output


class OllamaLLMModel(LLMModel):
    def setup(self, config):
        return None

    def ollama_chat(self, messages, temperature, response_format=None):
        headers = {
            "Content-Type": "application/json"
        }
        params = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if response_format:
            params["response_format"] = response_format

        response = requests.post(
            url=f"{self._base_url}/chat/completions",
            headers=headers,
            json=params,
            stream=False,
            timeout=300
        )
        return response.json()

    def _completion(self, prompt, return_type, temperature=0.5):
        import json
        
        # Generate JSON schema from the Pydantic model for structured output
        response_format = None
        if return_type is not None:
            try:
                schema = return_type.model_json_schema()
                response_format = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": return_type.__name__,
                        "strict": True,
                        "schema": schema
                    }
                }
            except Exception:
                pass
        
        messages = [{"role": "user", "content": prompt}]
        response = self.ollama_chat(messages=messages, temperature=temperature, response_format=response_format)
        
        if response and len(response.get("choices", [])) > 0:
            ret = response["choices"][0]["message"]["content"]
            # 从输出结果中过滤掉<think>标签内的文字，以免影响后续逻辑
            ret = re.sub(r"<think>.*</think>", "", ret, flags=re.DOTALL)
            
            # Parse and validate the response using the Pydantic model
            if return_type is not None:
                try:
                    # Try to parse as JSON and validate with Pydantic
                    parsed = json.loads(ret)
                    validated = return_type.model_validate(parsed)
                    return validated.res
                except json.JSONDecodeError:
                    # If JSON parsing fails, try to extract JSON from the text
                    json_match = re.search(r'\{.*\}', ret, re.DOTALL)
                    if json_match:
                        try:
                            parsed = json.loads(json_match.group())
                            validated = return_type.model_validate(parsed)
                            return validated.res
                        except (json.JSONDecodeError, Exception):
                            pass
                    # If all parsing fails, return the raw text
                    return ret
                except Exception as e:
                    print(f"OllamaLLMModel: Failed to validate response: {e}")
                    return ret
            return ret
        return ""


def create_llm_model(llm_config):
    """Create llm model. provider 支持：openai / ollama / vllm。"""
    provider = llm_config.get("provider", "openai")
    if provider == "ollama":
        return OllamaLLMModel(llm_config)
    if provider == "openai":
        return OpenAILLMModel(llm_config)
    if provider == "vllm":
        return VLLMLocalModel(llm_config)
    raise NotImplementedError(f"llm provider {provider} is not supported")
