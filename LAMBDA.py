import shutil
import gradio as gr
import json
import time
from core.conversation import Conversation
from prompt_engineering.prompts import *
import yaml
from utils.utils import *
import sys
import os


class LAMBDA:
    def __init__(self, config_path='config.yaml'):
        ensure_config_file("config.yaml")
        print("Try to load config: ", config_path)

        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            bundle_dir = os.path.dirname(sys.executable)
        else:
            bundle_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(bundle_dir, config_path)

        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.load(f, Loader=yaml.FullLoader)
        if self.config["load_chat"] == True:
            self.load_dialogue(self.config["chat_history_path"])
        else:
            self.session_cache_path = self.init_local_cache_path(to_absolute_path(self.config["project_cache_path"]))
            self.config["session_cache_path"] = self.session_cache_path
        print("Session cache path: ", self.session_cache_path)
        self.conv = Conversation(self.config)

        self.conv.programmer.messages = [
            {
                "role": "system",
                "content": PROGRAMMER_PROMPT.format(working_path=self.session_cache_path)
            }
        ]

        if self.conv.retrieval:
            self.conv.programmer.messages[0]["content"] += KNOWLEDGE_INTEGRATION_SYSTEM
            
        # [NEW] CỤM BIẾN TIẾN HÓA (Evolvable Variables)
        # LLM (Solver) được phép trực tiếp sửa đổi các con số này trong quá trình mutate!
        self.epiplexity_min = 0.5   # Ngưỡng dưới của Vùng Goldilocks
        self.epiplexity_max = 2.2   # Ngưỡng trên của Vùng Goldilocks
        self.vocab_dropout_rate = 0.15 # Tỷ lệ chặn từ vựng ép Proposer sáng tạo

    def get_evolution_params(self):
        """Hàm này export cấu hình hiện tại để lưu vào Archive hoặc in ra log."""
        return {
            "epiplexity_min": getattr(self, 'epiplexity_min', 0.5),
            "epiplexity_max": getattr(self, 'epiplexity_max', 2.2),
            "vocab_dropout_rate": getattr(self, 'vocab_dropout_rate', 0.15)
        }


    def init_local_cache_path(self, project_cache_path):
        current_fold = time.strftime('%Y-%m-%d', time.localtime())
        hsid = str(hash(id(self)))
        session_cache_path = os.path.join(project_cache_path, current_fold + '-' + hsid)
        if not os.path.exists(session_cache_path):
            os.makedirs(session_cache_path)
        return session_cache_path

    def open_board(self):
        return self.conv.show_data()

    def add_file(self, files):
        file_path = files.name
        shutil.copy(file_path, self.session_cache_path)
        filename = os.path.basename(file_path)
        file_extension = os.path.splitext(file_path)[1].lower()
        self.conv.file_list.append(filename)
        local_cache_path = os.path.join(self.session_cache_path, filename)

        DATA_EXTS = ['.xlsx', '.xls', '.csv', '.ods']
        if file_extension in DATA_EXTS:
            try:
                self.conv.add_data(local_cache_path)
                gen_info = self.conv.my_data_cache.get_description()
                self.conv.programmer.messages[0][
                    "content"] += f"\n\n[SYSTEM ALERT: USER UPLOADED A NEW DATASET]\nYou MUST use this EXACT file path to read the data in your Python code: '{local_cache_path}'.\nDo NOT use any other path. The file is a dataset with the following general information:\n{gen_info}.\nYou should care about the missing values and type of each column in your later processing."
                print(f"Data loaded successfully: {filename}")
                status_msg = f"✅ **File uploaded:** `{filename}`\n- Rows: {gen_info['num_rows']}, Columns: {gen_info['num_features']}\n- Features: {', '.join(str(c) for c in gen_info['features'][:10])}"
            except Exception as e:
                print(f"Warning: Could not parse data file '{filename}': {e}")
                self.conv.programmer.messages[0][
                    "content"] += f"\nNow, user uploads the file in {local_cache_path} (could not auto-parse, please load it manually in code)."
                status_msg = f"⚠️ **File uploaded but could not be parsed:** `{filename}` ({e})"
        else:
            self.conv.programmer.messages[0][
                "content"] += f"\nNow, user uploads the files in {local_cache_path}."
            status_msg = f"📎 **File uploaded:** `{filename}`"

        print(f"Upload file in gradio path: {file_path}, local cache path: {local_cache_path}")
        return [{"role": "assistant", "content": status_msg}]

    def rendering_code(self):
        return self.conv.rendering_code()

    def generate_report(self, chat_history):
        legacy_history = []
        user_msg = None
        for msg in chat_history:
            if isinstance(msg, dict):
                if msg["role"] == "user":
                    user_msg = msg.get("content", "")
                elif msg["role"] == "assistant" and user_msg is not None:
                    legacy_history.append([user_msg, msg.get("content", "")])
                    user_msg = None
            elif isinstance(msg, (list, tuple)):
                legacy_history.append(msg)
        down_path = self.conv.document_generation(legacy_history)
        return [gr.Button(visible=False), gr.DownloadButton(label=f"Download Report", value=down_path, visible=True)]

    def export_code(self):
        down_path = self.conv.export_code()
        return [gr.Button(visible=False), gr.DownloadButton(label=f"Download Notebook", value=down_path, visible=True)]

    def down_report(self):
        return [gr.Button(visible=True), gr.DownloadButton(visible=False)]

    def down_notebook(self):
        return [gr.Button(visible=True), gr.DownloadButton(visible=False)]

    def chat_streaming(self, message, chat_history, code=None):
        if not code:
            self.conv.programmer.messages.append({"role": "user", "content": message})
        else:
            message = code
        chat_history = chat_history + [
            {"role": "user", "content": message},
            {"role": "assistant", "content": ""}
        ]
        return "", chat_history

    def save_dialogue(self, chat_history):
        self.conv.save_conv()
        with open(os.path.join(self.session_cache_path, 'system_dialogue.json'), 'w') as f:
            json.dump(chat_history, f, indent=4)
        print(f"Dialogue saved in {os.path.join(self.session_cache_path, 'system_dialogue.json')}.")

    def load_dialogue(self, dialogue_path):
        try:
            system_dialogue_path = os.path.join(dialogue_path, 'system_dialogue.json')
            system_config_path = os.path.join(dialogue_path, 'config.json')
            with open(system_dialogue_path, 'r') as f:
                chat_history = json.load(f)
            with open(system_config_path, 'r') as f:
                sys_config = json.load(f)
            self.session_cache_path = sys_config["session_cache_path"]
            self.config["session_cache_path"] = self.session_cache_path
            self.config["chat_history_display"] = chat_history
            self.config["figure_list"] = sys_config["figure_list"]
            return chat_history
        except Exception as e:
            print(f"Failed to load the chat history: {e}")
            return []

    def clear_all(self, message, chat_history):
        self.conv.clear()
        return "", []

    def update_config(self, conv_model, programmer_model, inspector_model, api_key,
                      base_url_conv_model, base_url_programmer, base_url_inspector,
                      max_attempts, max_exe_time,
                      load_chat, chat_history_path):

        self.conv.update_config(conv_model=conv_model, programmer_model=programmer_model, inspector_model=inspector_model, api_key=api_key,
                      base_url_conv_model=base_url_conv_model, base_url_programmer=base_url_programmer, base_url_inspector=base_url_inspector,
                      max_attempts=max_attempts, max_exe_time=max_exe_time)

        if load_chat == True:
            self.config['chat_history_path'] = chat_history_path
            chat_history = self.load_dialogue(chat_history_path)
            self.config['load_chat'] = load_chat
            return ["### Config Updated!", chat_history]

        return "### Config Updated!", []
