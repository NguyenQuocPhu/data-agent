import os
import re
import openai
import json
import random
from triadic_dgm.agent.programmer import Programmer
from triadic_dgm.agent.verifier import SemanticVerifier
import pandas as pd
from triadic_dgm.prompts.prompts import *
from triadic_dgm.benchmark.core.proposer_agent import ProposerAgent
from triadic_dgm.benchmark.implementations.llm_unified import UnifiedLLMClient
from triadic_dgm.benchmark.core.evolution_hyperparams import HYPERPARAMS
import warnings
import traceback
import zipfile
from triadic_dgm.sandbox.kernel import *
from ui.display import *
from pathlib import Path
from utils.utils import *


class TriadicAgent:

    def __init__(self, config) -> None:
        self.config = config    
        self.client = openai.OpenAI(api_key=config['api_key'], base_url=config['base_url_conv_model'])
        self.model = config['conv_model']
        self.programmer = Programmer(api_key=config['api_key'], model=config['programmer_model'],
                                     base_url=config['base_url_programmer'])
        self.verifier = SemanticVerifier(api_key=config['api_key'], model=config['inspector_model'],
                                        base_url=config['base_url_inspector'])
        self.proposer = ProposerAgent(UnifiedLLMClient(config['programmer_model']))
        self.session_cache_path = config["session_cache_path"]
        self.chat_history_display = config["chat_history_display"] if "chat_history_display" in config else []
        self.retrieval = self.config['retrieval']
        self.kernel = CodeKernel(session_cache_path=self.session_cache_path, max_exe_time=config['max_exe_time'])
        self.max_attempts = config['max_attempts']
        self.error_count = 0
        self.repair_count = 0
        self.file_list = []
        self.figure_list = config["figure_list"] if "figure_list" in config else []
        self.function_repository = {}
        self.run_code(IMPORT)

    def add_functions(self, function_lib: dict) -> None:
        self.function_repository = function_lib

    def check_folder(self):
        current_files = os.listdir(self.session_cache_path)
        new_files = set(current_files) - set(self.file_list)
        self.file_list = current_files
        display = False
        display_link = ''
        if new_files:
            display = True
            for file in new_files:
                file_link = os.path.join(self.session_cache_path,file)
                absolute_path = str(Path(file_link).resolve()).replace('\\', '/')
                if os.path.splitext(file)[1] in ['.png','.jpg','.jpeg']:
                    display_link += display_image(absolute_path)
                    print("absolute_path:", absolute_path)
                    self.figure_list.append(absolute_path)
                else:
                    display_link += display_download_file(absolute_path, file)
        try:
            print("display_link:", display_link)
        except UnicodeEncodeError:
            pass
        return display, display_link


    def save_conv(self):
        with open(os.path.join(self.session_cache_path, 'programmer_msg.json'), 'w') as f:
            json.dump(self.programmer.messages, f, indent=4)
            f.close()
        print(f"Conversation saved in {os.path.join(self.session_cache_path, 'programmer_msg.json')}")
        with open(os.path.join(self.session_cache_path, 'verifier_memory.json'), 'w') as f:
            json.dump([r.to_dict() for r in self.verifier.memory_bank.rules], f, indent=4)
            f.close()
        print(f"Verifier memory saved in {os.path.join(self.session_cache_path, 'verifier_memory.json')}")
        with open(os.path.join(self.session_cache_path, 'config.json'), 'w') as f:
            config = {
            "config": self.config,
            "model": self.model,
            "session_cache_path": self.session_cache_path,
            "chat_history_display": self.chat_history_display,
            "retrieval": self.retrieval,
            "max_attempts": self.max_attempts,
            "error_count": self.error_count,
            "repair_count": self.repair_count,
            "file_list": [str(p) for p in self.file_list],
            "figure_list": [str(p) for p in self.figure_list],
            "function_repository": self.function_repository,
        }
            json.dump(config, f, indent=4)
        print(f"Config saved in {os.path.join(self.session_cache_path, 'config.json')}")

    def add_programmer_msg(self, message: dict):
        self.programmer.messages.append(message)

    def add_programmer_repair_msg(self, bug_code: str, error_msg: str, fix_method: str, role="user"):
        message = {"role": role,
                   "content": CODE_FIX.format(bug_code=bug_code, error_message=error_msg, fix_method=fix_method)}
        self.programmer.messages.append(message)

    # add_inspector_msg REMOVED — replaced by SemanticVerifier.verify_syntax()

    def run_code(self, code):
        try:
            sign, msg_llm, exe_res = execute(code, self.kernel)
        except Exception as e:
            print(f'Error in executing code (outer): {e}')
            sign, msg_llm, exe_res = 'text', f'{e}\nThis error is due to the outer programme, not the error in the kernel, you should tell the user to check the system code.', str(e)

        return sign, msg_llm, exe_res

    def rendering_code(self):
        for i in range(len(self.programmer.messages) - 1, 0, -1):
            if self.programmer.messages[i]["role"] == "assistant":
                is_python, code = extract_code(self.programmer.messages[i]["content"])
                if is_python:
                    return code
        return None

    def show_data(self) -> pd.DataFrame:
        print("Data is now handled via Workspace Active Datasets and load_dataset.")
        return pd.DataFrame()

    def document_generation(self, chat_history):
        print("Report generating...")
        formatted_chat = []
        for item in chat_history:
            formatted_chat.append({"role": "user", "content": item[0]})
            formatted_chat.append({"role": "assistant", "content": item[1]})
        self.messages = [{"role": "system", "content": Basic_Report}] + formatted_chat + [{"role": "user", "content": f"Now, you should generate a report according to the above chat history (Do not give further suggestions at the end of report).\nNote: Here is figure list with links in the chat history: {self.figure_list}"}]
        report = self.call_chat_model().choices[0].message.content
        self.messages.append({"role": "assistant", "content": report})
        mkd_path = os.path.join(self.session_cache_path, 'report.md')
        with open(mkd_path, "w") as f:
            f.write(report)
            f.close()
        return mkd_path

    def export_code(self):
        print("Exporting notebook...")
        notebook_path = os.path.join(self.session_cache_path, 'notebook.ipynb')
        try:
            self.kernel.write_to_notebook(notebook_path)
        except Exception as e:
            print(f"An error occurred when exporting notebook: {e}")
        return notebook_path

    def call_chat_model(self, functions=None, include_functions=False):
        params = {
            "model": self.model,
            "messages": self.messages,
        }

        if include_functions:
            params["functions"] = functions
            params["function_call"] = "auto"

        return self.client.chat.completions.create(**params)


    def clear(self):
        clear_working_path(self.session_cache_path)
        self.messages = []
        self.programmer.clear()
        self.verifier.clear()
        self.kernel.shutdown()
        del self.kernel
        self.kernel = CodeKernel(session_cache_path=self.session_cache_path, max_exe_time=self.config['max_exe_time'])


    def stream_workflow(self, chat_history_display, code=None) -> object:
        try:
            if not chat_history_display or chat_history_display[-1].get("role") != "assistant":
                chat_history_display.append({"role": "assistant", "content": ""})
            chat_history_display[-1]["content"] = ""
            yield chat_history_display
            if code is not None:
                prog_response = HUMAN_LOOP.format(code=code)
                self.add_programmer_msg({"role": "user", "content": prog_response})
            else:
                # Kích hoạt ProposerAgent để sinh Vocab Dropout trước khi gọi LLM (Chỉ với Business Tasks)
                try:
                    task_context = chat_history_display[-2]["content"] if len(chat_history_display) >= 2 else "Phân tích dữ liệu"
                    if self.verifier.is_business_task(task_context):
                        # Dùng Proposer để lên kế hoạch và lấy lệnh cấm từ vựng
                        plan = self.proposer.propose_plan(task_context, "Active Data Workspace")
                        
                        # Bắt từ vựng bị cấm nếu có sinh ra
                        dropout_rate = getattr(HYPERPARAMS, 'vocab_dropout_rate', 0.2)
                        banned_words = []
                        if self.proposer.history_concepts and random.random() <= dropout_rate:
                            banned_words = random.sample(self.proposer.history_concepts, max(1, int(len(self.proposer.history_concepts) * dropout_rate)))
                            if banned_words:
                                vocab_msg = f"<!-- VOCAB_DROPOUT: {', '.join(banned_words)} -->\n"
                                chat_history_display[-1]["content"] += vocab_msg
                                yield chat_history_display
                                # Inject lệnh cấm này thẳng vào User Prompt để ép LLM không dùng
                                banned_instruction = f"VOCAB DROPOUT CONSTRAINT: CẤM SỬ DỤNG các phương pháp/từ khóa sau: {', '.join(banned_words)}. Hãy tìm hướng tiếp cận khác.\n\n"
                                self.add_programmer_msg({"role": "user", "content": banned_instruction})
                except Exception as e:
                    print(f"Lỗi Proposer: {e}")

                prog_response = ''
                code_started = False
                for message in self.programmer._call_chat_model_streaming(retrieval=self.retrieval, kernel=self.kernel):
                    prev_prog = prog_response
                    prog_response += message
                    if not code_started and "```python" in prog_response:
                        code_started = True
                    if code_started and prog_response.count("```") >= 2:
                        idx = prog_response.find("```", prog_response.find("```python") + 9)
                        if idx != -1:
                            # We found the closing backticks!
                            # Cut the message to just include the closing backticks
                            excess = len(prog_response) - (idx + 3)
                            if excess > 0:
                                message = message[:-excess]
                            prog_response = prog_response[:idx + 3]
                            chat_history_display[-1]["content"] += message
                            yield chat_history_display
                            break # Force stop the LLM stream!
                    
                    chat_history_display[-1]["content"] += message
                    yield chat_history_display
                    
                self.add_programmer_msg({"role": "assistant", "content": prog_response})

            step = 0
            max_steps = 5

            while step < max_steps:
                is_python, code = extract_code(prog_response)
                print("is_python:", is_python)

                if not is_python:
                    import re
                    is_json_requested = any("CRITICAL RULE" in msg.get("content", "") for msg in self.programmer.messages)
                    if is_json_requested and not re.search(r'```json', prog_response):
                        chat_history_display[-1]["content"] += '\n\n⭕ Verifier Error: Missing JSON block. Requesting regeneration...\n'
                        yield chat_history_display
                        
                        self.add_programmer_msg({"role": "user", "content": "You MUST output the JSON block wrapped in ```json ```. Please provide the JSON block containing the Execution Trace directly in your markdown response now using the exact schema specified in the CRITICAL RULE."})
                        prog_response = ''
                        for message in self.programmer._call_chat_model_streaming(retrieval=self.retrieval, kernel=self.kernel):
                            chat_history_display[-1]["content"] += message
                            yield chat_history_display
                            prog_response += message
                        self.add_programmer_msg({"role": "assistant", "content": prog_response})
                        
                        step += 1
                        continue
                    break

                chat_history_display[-1]["content"] += '\n🖥️ Execute code...'
                yield chat_history_display
                sign, msg_llm, exe_res = self.run_code(code)
                try:
                    print("Executing result:", exe_res)
                except UnicodeEncodeError:
                    print("Executing result (Unicode hidden for console compatibility)")
                if sign and 'error' not in sign:
                    prog_response = yield from self._handle_execution_result(exe_res, msg_llm, chat_history_display)
                    break
                else:
                    self.error_count += 1
                    round = 0
                    while 'error' in sign and round < self.max_attempts:
                        # Append the actual raw error trace (msg_llm) to the chat history so the UI and User can see what crashed
                        chat_history_display[-1]["content"] += f'\n<Error_Trace>\n{msg_llm}\n</Error_Trace>\n⭕ Execution error, try to repair the code, attempts: {round + 1}....\n'
                        yield chat_history_display
                        user_task = self._get_user_task()
                        if round == 3:
                            insp_response = "Try other packages or methods."
                        else:
                            insp_response = self.verifier.verify_syntax(code, msg_llm, user_task)
                            chat_history_display[-1]["content"] += f'\n🕵️ **Inspector Hypotheses:**\n> ' + insp_response.replace('\n', '\n> ') + '\n\n'
                            yield chat_history_display

                        self.add_programmer_repair_msg(code, msg_llm, insp_response)
                        prog_response = ''
                        code_started = False
                        for message in self.programmer._call_chat_model_streaming():
                            prog_response += message
                            if not code_started and "```python" in prog_response:
                                code_started = True
                            if code_started and prog_response.count("```") >= 2:
                                idx = prog_response.find("```", prog_response.find("```python") + 9)
                                if idx != -1:
                                    excess = len(prog_response) - (idx + 3)
                                    if excess > 0:
                                        message = message[:-excess]
                                    prog_response = prog_response[:idx + 3]
                                    chat_history_display[-1]["content"] += message
                                    yield chat_history_display
                                    break
                            
                            chat_history_display[-1]["content"] += message
                            yield chat_history_display
                        chat_history_display[-1]["content"] += '\n🖥️ Execute code...\n'
                        yield chat_history_display
                        self.add_programmer_msg({"role": "assistant", "content": prog_response})
                        is_python, code = extract_code(prog_response)
                        if is_python:
                            sign, msg_llm, exe_res = self.run_code(code)
                            if sign and 'error' not in sign:
                                self.repair_count += 1
                                break
                        round += 1

                    if round == self.max_attempts:
                        chat_history_display[-1]["content"] += f'\n<Error_Trace>\n{msg_llm}\n</Error_Trace>\n'
                        chat_history_display[-1]["content"] += f"\nSorry, I can't fix the code with {self.max_attempts} attempts, can you help me to modified it or give some suggestions?"
                        yield chat_history_display
                        return

                    prog_response = yield from self._handle_execution_result(exe_res, msg_llm, chat_history_display)
                    break
                
                step += 1

        except Exception as e:
            chat_history_display[-1]["content"] += "\nSorry, there is an error in the program, please try again."
            yield chat_history_display
            print(f"An error occurred: {e}")
            traceback.print_exc()
            if self.programmer.messages[-1]["role"] == "user":
                self.programmer.messages.append({"role": "assistant", "content": f"An error occurred in program: {e}"})

    def _get_user_task(self) -> str:
        """Extract the user's original question from conversation history."""
        for msg in reversed(self.programmer.messages):
            if msg["role"] == "user":
                content = msg.get("content", "")
                # Skip system-generated messages
                if content.startswith("⚠️") or content.startswith("This is the executing result"):
                    continue
                if "SEMANTIC VERIFICATION FAILED" in content:
                    continue
                if "You should attempt to fix" in content:
                    continue
                return content
        return ""

    def _get_last_code(self) -> str:
        """Extract the last Python code from programmer messages."""
        for msg in reversed(self.programmer.messages):
            if msg["role"] == "assistant":
                is_python, code = extract_code(msg.get("content", ""))
                if is_python:
                    return code
        return ""

    def _handle_execution_result(self, exe_res, msg_llm, chat_history_display):
        chat_history_display[-1]["content"] += display_exe_results(exe_res)
        yield chat_history_display

        display, link_info = self.check_folder()
        chat_history_display[-1]["content"] += f"{link_info}" if display else ''

        # TRUNCATE msg_llm to prevent 400 Bad Request and LLM Gateway Timeout, but never cut into the
        # [JSON_START_PERSONA]...[JSON_END_PERSONA] block — persona profiling data can push this past
        # 4000 chars, and a truncated tail marker would break ReportGenerator.generate_markdown_report().
        if len(msg_llm) > 4000:
            json_match = re.search(r'\[JSON_START_PERSONA\].*?\[JSON_END_PERSONA\]', msg_llm, re.DOTALL)
            if json_match:
                before, json_block, after = msg_llm[:json_match.start()], json_match.group(0), msg_llm[json_match.end():]
                before = before[-1000:] if len(before) > 1000 else before
                after = after[:1000] if len(after) > 1000 else after
                msg_llm = f"{before}\n...[TRUNCATED_DUE_TO_LENGTH]...\n{json_block}\n...[TRUNCATED_DUE_TO_LENGTH]...\n{after}"
            else:
                msg_llm = msg_llm[:2000] + "\n...[TRUNCATED_DUE_TO_LENGTH]...\n" + msg_llm[-2000:]

        # ========== SEMANTIC VERIFICATION GATE (Chiều 2) ==========
        user_task = self._get_user_task()
        if self.verifier.is_business_task(user_task):
            last_code = self._get_last_code()
            chat_history_display[-1]["content"] += (
                "\n\n🔍 **Semantic Verification Pipeline:**\n"
                "- [x] Kiểm tra Logic bằng 12 Hard Gates nghiệp vụ\n"
                "- [x] Quét lỗi Ảo Giác Nhân Quả (Causal Hallucination)\n"
                "- [x] Quét lỗi mâu thuẫn Hành Động & Dữ Liệu\n"
                "- [x] Kiểm định Target Leakage\n"
                "- [ ] *Đang gọi AI Giám Khảo đọc hiểu báo cáo (Quá trình này tốn 30-60s tuỳ độ khó, vui lòng kiên nhẫn)...*\n"
            )
            yield chat_history_display

            verdict = self.verifier.verify_semantics(user_task, last_code, msg_llm)
            semantic_retry = 0
            MAX_SEMANTIC_RETRIES = 5

            while verdict.get("status") == "REVISE" and semantic_retry < MAX_SEMANTIC_RETRIES:
                feedback = verdict.get("feedback", "Missing business metrics")
                missing = verdict.get("missing", [])

                chat_history_display[-1]["content"] += (
                    f"\n⚠️ **Verifier REVISE** (Attempt {semantic_retry + 1}/{MAX_SEMANTIC_RETRIES}):\n"
                    f"   {feedback}\n"
                    f"   Missing: {', '.join(missing) if missing else 'N/A'}\n"
                )

                # Inject hidden RIMRULE tag for the frontend Toast
                if "new_rule" in verdict:
                    rule_text = verdict["new_rule"].replace("\n", " ")
                    chat_history_display[-1]["content"] += f"\n<!-- RIMRULE_LEARNED: {rule_text} -->\n"

                yield chat_history_display

                # Send fix instruction to Programmer
                fix_prompt = SEMANTIC_FIX.format(feedback=feedback)
                self.add_programmer_msg({"role": "user", "content": fix_prompt})

                # Stream new code from Programmer - add separator so UI doesn't merge with old content
                chat_history_display[-1]["content"] += f'\n\n<Retry attempt="{semantic_retry + 1}">\n'
                yield chat_history_display
                prog_response = ''
                code_started = False
                for message in self.programmer._call_chat_model_streaming():
                    prog_response += message
                    if not code_started and "```python" in prog_response:
                        code_started = True
                    if code_started and prog_response.count("```") >= 2:
                        idx = prog_response.find("```", prog_response.find("```python") + 9)
                        if idx != -1:
                            excess = len(prog_response) - (idx + 3)
                            if excess > 0:
                                message = message[:-excess]
                            prog_response = prog_response[:idx + 3]
                            chat_history_display[-1]["content"] += message
                            yield chat_history_display
                            break
                    chat_history_display[-1]["content"] += message
                    yield chat_history_display
                chat_history_display[-1]["content"] += '\n</Retry>\n'
                yield chat_history_display
                self.add_programmer_msg({"role": "assistant", "content": prog_response})

                # Execute new code
                is_python, new_code = extract_code(prog_response)
                if not is_python:
                    break

                chat_history_display[-1]["content"] += '\n🖥️ Execute code...\n'
                yield chat_history_display
                sign, msg_llm_new, exe_res_new = self.run_code(new_code)

                if sign and 'error' not in sign:
                    msg_llm = msg_llm_new
                    chat_history_display[-1]["content"] += display_exe_results(exe_res_new)
                    yield chat_history_display
                    # Re-verify semantics
                    verdict = self.verifier.verify_semantics(user_task, new_code, msg_llm)
                else:
                    verdict = {"status": "REVISE", "feedback": f"Code crashed: {msg_llm_new[:500]}", "missing": ["working code"]}

                semantic_retry += 1

            # Final verdict display
            if verdict.get("status") == "ACCEPT":
                epi = verdict.get("epiplexity_score", 0)
                chat_history_display[-1]["content"] += f"\n✅ **Verifier: ACCEPTED** (Epiplexity: {epi:.2f})\n"
            else:
                chat_history_display[-1]["content"] += "\n⚠️ **Verifier: Max retries exceeded.** Showing best available result.\n"
            yield chat_history_display
        # ========== END SEMANTIC VERIFICATION GATE ==========

        # Prune conversation history if it gets too long
        if len(self.programmer.messages) > 10:
            self.programmer.messages = [self.programmer.messages[0]] + self.programmer.messages[-6:]

        # ========== MỚI: Tích hợp Structured Output (SOLID) ==========
        from triadic_dgm.services.report_generator import ReportGenerator
        
        chat_history_display[-1]["content"] += "\n\n**[Hệ thống đang sinh Báo cáo phân tích...]**\n\n"
        yield chat_history_display

        prog_response = ''
        try:
            print(f"DEBUG: Calling LLM via Instructor for Structured Output.")
            generator = ReportGenerator(
                api_key=self.config['api_key'],
                base_url=self.config['base_url_programmer'],
                model_name=self.config['programmer_model']
            )
            # Dùng msg_llm (Raw JSON Python Output) làm input
            prog_response = generator.generate_markdown_report(msg_llm)
            
            # CHÚ Ý: KHÔNG ĐƯỢC REPLACE CHUỖI CŨ, SẼ LÀM HỎNG LOGIC STREAMING CỦA NEXT.JS
            chat_history_display[-1]["content"] += prog_response
            yield chat_history_display
            
        except Exception as e:
            print(f"DEBUG LLM CALL FAILED: {e}")
            chat_history_display[-1]["content"] += f"\n[LLM ERROR: {e}]\n"
            yield chat_history_display

        self.add_programmer_msg({"role": "assistant", "content": prog_response})
        chat_history_display[-1]["content"] = display_suggestions(prog_response, chat_history_display[-1]["content"])
        yield chat_history_display
        return prog_response

    
    def update_config(self, conv_model, programmer_model, inspector_model, api_key,
                      base_url_conv_model, base_url_programmer, base_url_inspector,
                      max_attempts, max_exe_time):

        if self.config['api_key'] != api_key:
            self.config['api_key'] = api_key
            self.client = openai.OpenAI(api_key=api_key, base_url=base_url_conv_model)
            self.programmer.client = openai.OpenAI(api_key=api_key, base_url=base_url_programmer)
            self.inspector.client = openai.OpenAI(api_key=api_key, base_url=base_url_inspector)

        if self.model != conv_model:
            self.model = conv_model
            self.config['conv_model'] = conv_model

        if self.kernel.max_exe_time != max_exe_time:
            self.kernel.max_exe_time = max_exe_time
            self.config['max_exe_time'] = max_exe_time

        if self.programmer.model != programmer_model:
            self.programmer.model = programmer_model
            self.config['programmer_model'] = programmer_model

        if self.verifier.model != inspector_model:
            self.verifier.model = inspector_model
            self.config['inspector_model'] = inspector_model

        if self.max_attempts != max_attempts:
            self.config['max_attempts'] = max_attempts
