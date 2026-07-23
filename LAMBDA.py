import shutil
import gradio as gr
import json
import time
import random
import logging
from triadic_dgm import TriadicAgent
from triadic_dgm.prompts.prompts import *
from langgraph_agent import DataAgentGraph
import yaml
from utils.utils import *
import sys
import os
from datetime import datetime
import pandas as pd
import numpy as np
import re

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('lambda_evolution.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('LAMBDA_Evolution')

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
            
        if 'api_key' not in self.config and 'api_key_env_var' in self.config:
            self.config['api_key'] = os.environ.get(self.config['api_key_env_var'], 'dummy_key')
        elif 'api_key' not in self.config:
            self.config['api_key'] = 'dummy_key'
        
        # [NEW] CỤM BIẾN TIẾN HÓA (Evolvable Variables) - MUTATED WITH DRIFT
        # Apply evolutionary drift to hyperparameters for Polyglot Benchmark optimization
        self.epiplexity_min = self._mutate_param(
            getattr(self, 'epiplexity_min', 0.5),
            -0.1, 0.1, 0.5
        )
        self.epiplexity_max = self._mutate_param(
            getattr(self, 'epiplexity_max', 2.2),
            -0.1, 0.1, 3.0
        )
        self.vocab_dropout_rate = self._mutate_param(
            getattr(self, 'vocab_dropout_rate', 0.15),
            -0.1, 0.1, 0.5
        )
        
        # Ensure epiplexity_min < epiplexity_max with buffer
        if self.epiplexity_min >= self.epiplexity_max:
            self.epiplexity_min = self.epiplexity_max - 0.3
        
        # Validate parameter ranges
        self.epiplexity_min = max(0.1, min(self.epiplexity_min, 1.0))
        self.epiplexity_max = max(0.5, min(self.epiplexity_max, 4.0))
        self.vocab_dropout_rate = max(0.05, min(self.vocab_dropout_rate, 0.8))
        
        if self.config["load_chat"] == True:
            self.load_dialogue(self.config["chat_history_path"])
        else:
            self.session_cache_path = self.init_local_cache_path(to_absolute_path(self.config["project_cache_path"]))
            self.config["session_cache_path"] = self.session_cache_path
        
        print("Session cache path: ", self.session_cache_path)
        
        # Initialize conversation with proper error handling
        try:
            self.conv = TriadicAgent(self.config)
            logger.info("TriadicAgent initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize TriadicAgent: {e}")
            raise

        safe_working_path = str(self.session_cache_path).replace('\\', '/')
        self.conv.programmer.messages = [
            {
                "role": "system",
                "content": PROGRAMMER_PROMPT.format(working_path=safe_working_path)
            }
        ]

        if self.conv.retrieval:
            self.conv.programmer.messages[0]["content"] += KNOWLEDGE_INTEGRATION_SYSTEM

        # ── LangGraph wrapper (Phase 1) ─────────────────────────────────────
        # DataAgentGraph wraps the existing TriadicAgent into a LangGraph
        # StateGraph. Set USE_LANGGRAPH=False to fall back to the old engine.
        self.USE_LANGGRAPH = True
        self.lg_graph = DataAgentGraph(self.conv)

        # Log evolutionary parameters
        logger.info(f"Evolutionary Parameters - epiplexity_min: {self.epiplexity_min}, "
                   f"epiplexity_max: {self.epiplexity_max}, vocab_dropout_rate: {self.vocab_dropout_rate}")

    def _mutate_param(self, current_value, min_step, max_step, max_value):
        """Apply evolutionary drift mutation to hyperparameters."""
        mutation = random.uniform(min_step, max_step)
        new_value = current_value + mutation
        return max(0.0, min(new_value, max_value))

    def get_evolution_params(self):
        """Hàm này export cấu hình hiện tại để lưu vào Archive hoặc in ra log."""
        return {
            "epiplexity_min": getattr(self, 'epiplexity_min', 0.5),
            "epiplexity_max": getattr(self, 'epiplexity_max', 2.2),
            "vocab_dropout_rate": getattr(self, 'vocab_dropout_rate', 0.15),
            "timestamp": datetime.now().isoformat()
        }

    def init_local_cache_path(self, project_cache_path):
        current_fold = time.strftime('%Y-%m-%d', time.localtime())
        hsid = str(hash(id(self)))
        session_cache_path = os.path.join(project_cache_path, current_fold + '-' + hsid)
        if not os.path.exists(session_cache_path):
            try:
                os.makedirs(session_cache_path)
                logger.info(f"Created session cache directory: {session_cache_path}")
            except OSError as e:
                logger.error(f"Failed to create cache directory: {e}")
                raise
        return session_cache_path

    def open_board(self):
        try:
            return self.conv.show_data()
        except Exception as e:
            logger.error(f"Error in open_board: {e}")
            return []

    def _load_known_column_descriptions(self):
        """Quét các file *_metadata.json ở root repo (vd data_processed_t4_metadata.json) — mỗi
        file có dạng {{"columns": [{{"column": ..., "description": ...}}, ...]}} do
        generate_metadata.py/update_metadata.py duy trì thủ công. Trả về list các dict
        {{column_name: description}}, mỗi phần tử ứng với 1 file metadata tìm được. Lỗi đọc file
        (JSON hỏng, thiếu field...) chỉ bị bỏ qua file đó, không làm crash refresh_workspace_context."""
        import glob
        repo_root = os.path.dirname(os.path.abspath(__file__))
        desc_maps = []
        for meta_path in glob.glob(os.path.join(repo_root, "*_metadata.json")):
            try:
                with open(meta_path, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                cols = meta.get("columns", [])
                if isinstance(cols, list) and cols and isinstance(cols[0], dict):
                    desc_map = {c["column"]: c.get("description", "") for c in cols if "column" in c}
                    if desc_map:
                        desc_maps.append(desc_map)
            except Exception as e:
                logger.warning(f"Skipping unreadable metadata file {meta_path}: {e}")
                continue
        return desc_maps

    def refresh_workspace_context(self, workspace_root: str):
        try:
            # [HOTFIX] Re-inject load_dataset to point to the correct session workspace instead of 'default'
            safe_workspace_dir = str(workspace_root).replace('\\', '/')
            tool_layer_code = f"""
import json
import pandas as pd
import os

_DATASET_CACHE = dict()

def load_dataset(file_id=None):
    \"\"\"Load a dataset by file_id or filename. If no argument, load the first available dataset.\"\"\"
    workspace_root = r'{safe_workspace_dir}'
    index_path = os.path.join(workspace_root, "index.json")
    if not os.path.exists(index_path):
        raise ValueError("No index.json found in workspace. Please upload a file first.")
        
    with open(index_path, 'r', encoding='utf-8') as f:
        index_data = json.load(f)
    
    if not index_data:
        raise ValueError("No datasets available. Please upload a file first.")
    
    if file_id is None:
        # Prefer entries with 'created_at' (newer format), pick the latest
        dated = [(fid, info.get('created_at','')) for fid, info in index_data.items() if info.get('created_at')]
        if dated:
            dated.sort(key=lambda x: x[1], reverse=True)
            file_id = dated[0][0]
        else:
            file_id = list(index_data.keys())[-1]
        print(f"Auto-selecting dataset: {{index_data[file_id].get('filename', file_id)}} (ID: {{file_id}})")
    
    if file_id in index_data:
        matched_id = file_id
    else:
        matched_id = None
        search = str(file_id).lower().strip()
        for fid, info in index_data.items():
            fname = info.get('filename', os.path.basename(info.get('path',''))).lower()
            if search == fname or search == os.path.splitext(fname)[0] or search in fname:
                matched_id = fid
                break
        if matched_id is None:
            available = ', '.join(f"'{{fid}}' ({{info.get('filename','?')}})" for fid, info in index_data.items())
            raise ValueError(f"File '{{file_id}}' not found. Available datasets: {{available}}")
    
    if matched_id in _DATASET_CACHE:
        return _DATASET_CACHE[matched_id]
    
    file_path = os.path.join(workspace_root, index_data[matched_id]['path'])
    if not os.path.exists(file_path):
        raise FileNotFoundError("File not found: " + str(file_path))
        
    ext = os.path.splitext(file_path)[1].lower()
    if ext in ['.csv', '.tsv']:
        df = pd.read_csv(file_path, sep='\\t' if ext == '.tsv' else ',')
    elif ext in ['.xlsx', '.xls']:
        df = pd.read_excel(file_path)
    else:
        raise ValueError("Unsupported extension " + ext)
        
    _DATASET_CACHE[matched_id] = df
    print(f"Loaded '{{index_data[matched_id].get('filename', matched_id)}}': {{len(df)}} rows x {{len(df.columns)}} columns")
    return df

def list_datasets():
    \"\"\"List all available datasets in the workspace.\"\"\"
    workspace_root = r'{safe_workspace_dir}'
    index_path = os.path.join(workspace_root, "index.json")
    if not os.path.exists(index_path):
        print("No datasets available.")
        return
    with open(index_path, 'r', encoding='utf-8') as f:
        index_data = json.load(f)
    if not index_data:
        print("No datasets available.")
        return
    print(f"Available datasets ({{len(index_data)}}):")
    for fid, info in index_data.items():
        print(f"  - load_dataset('{{fid}}')  # {{info.get('filename', fid)}}")
"""
            self.conv.run_code(tool_layer_code)

            index_path = os.path.join(workspace_root, "index.json")
            if not os.path.exists(index_path):
                return
                
            with open(index_path, 'r', encoding='utf-8') as f:
                index_data = json.load(f)
                
            if not index_data:
                return
                
            # Mô tả nghiệp vụ từng cột (tiếng Việt) được duy trì thủ công trong các file
            # *_metadata.json ở root repo (vd data_processed_t4_metadata.json) — metadata TỰ SINH
            # lúc upload (api/services/workspace.py:_save_uploads) chỉ có TÊN CỘT/dtype thô, không
            # có nghĩa nghiệp vụ, khiến LLM phải tự đoán ý nghĩa cột qua substring tên cột — đây
            # chính là nguyên nhân gốc của nhiều bug thật đã gặp trong session (fee_total bị chọn
            # nhầm thay vì fee_avg cho ARPU, cột services bị nhầm sang cột số...). Tự động so khớp
            # bộ cột đang active với các file *_metadata.json này, nếu khớp phần lớn thì bơm thẳng
            # mô tả từng cột vào context thay vì chỉ liệt kê 20 tên cột đầu trơn.
            known_desc_maps = self._load_known_column_descriptions()

            # Describe ONLY the dataset load_dataset() will actually return, not every file
            # ever uploaded to this workspace. DATA LEAKAGE OBSERVED LIVE: the workspace held
            # 4 retail datasets plus 3 telco ones, and this loop injected all of them with
            # their full per-column Vietnamese descriptions. The model then wrote its
            # behavioral_features list against the TELCO schema (cl_total_6m, LOYALTY_RANK,
            # OBJID_mask...) while load_dataset() returned the retail file — analysing one
            # dataset with another's column names. Showing a schema is enough to make the
            # model code against it, so only the active one may appear.
            tabular_exts = {'.csv', '.tsv', '.xlsx', '.xls', '.parquet'}
            tabular = [
                (fid, inf) for fid, inf in index_data.items()
                if os.path.splitext(inf.get('filename', inf.get('path', '')))[1].lower() in tabular_exts
            ]
            tabular.sort(key=lambda x: x[1].get('created_at', ''), reverse=True)
            active = tabular[:1] if tabular else list(index_data.items())[-1:]

            context_str = "\n\n[ACTIVE DATASET]\n"
            if len(index_data) > len(active):
                context_str += (
                    f"(Workspace còn {len(index_data) - len(active)} file cũ khác. "
                    f"Chúng KHÔNG liên quan tới phân tích này — `load_dataset()` chỉ trả về file bên dưới. "
                    f"TUYỆT ĐỐI KHÔNG dùng tên cột từ bất kỳ dataset nào khác.)\n"
                )
            for file_id, info in active:
                context_str += f"- File ID: {file_id}\n  Filename: {info.get('filename', os.path.basename(info.get('path', file_id)))}\n"

                # Load metadata
                meta_path = os.path.join(workspace_root, info.get("metadata_file", ""))
                if os.path.exists(meta_path):
                    with open(meta_path, 'r', encoding='utf-8') as mf:
                        meta = json.load(mf)
                        cols = meta.get("columns", [])

                        matched_desc_map = None
                        for desc_map in known_desc_maps:
                            if cols and len(set(cols) & set(desc_map.keys())) / len(cols) >= 0.5:
                                matched_desc_map = desc_map
                                break

                        if matched_desc_map:
                            context_str += (
                                f"  Metadata: {meta.get('size_bytes')} bytes, {len(cols)} cột.\n"
                                f"  Mô tả nghiệp vụ từng cột (DÙNG ĐỂ CHỌN ĐÚNG CỘT theo Ý NGHĨA, "
                                f"KHÔNG suy đoán qua substring tên cột):\n"
                            )
                            for c in cols:
                                desc = matched_desc_map.get(c)
                                context_str += f"    - {c}: {desc}\n" if desc else f"    - {c}\n"
                        else:
                            context_str += f"  Metadata: {meta.get('size_bytes')} bytes. Columns: {', '.join(cols[:20])}\n"

                        if 'dtypes' in meta:
                            dtypes = [f"{c} ({t})" for c, t in list(meta['dtypes'].items())[:10]]
                            context_str += f"  DTypes: {', '.join(dtypes)}\n"
                            
            context_str += "\nIMPORTANT:\nTo load this data, you MUST use the built-in function `load_dataset(file_id)`.\nExample: `df = load_dataset('abc12345')`\nDo NOT use pd.read_csv for these datasets!\n"
            
            # Clean up old ACTIVE DATASETS to avoid duplicate appending
            import re
            base_prompt = re.sub(r'\[ACTIVE DATASETS\].*', '', self.conv.programmer.messages[0]["content"], flags=re.DOTALL)
            self.conv.programmer.messages[0]["content"] = base_prompt.strip() + context_str
            
            logger.info("Workspace context refreshed successfully.")
        except Exception as e:
            logger.error(f"Error refreshing workspace context: {e}")

    def rendering_code(self):
        try:
            return self.conv.rendering_code()
        except Exception as e:
            logger.error(f"Error in rendering_code: {e}")
            return []

    def generate_report(self, chat_history):
        try:
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
            logger.info(f"Report generated: {down_path}")
            return [gr.Button(visible=False), gr.DownloadButton(label=f"Download Report", value=down_path, visible=True)]
        except Exception as e:
            logger.error(f"Error in generate_report: {e}")
            return [gr.Button(visible=False), gr.DownloadButton(label=f"Error: {e}", visible=True)]

    def export_code(self):
        try:
            down_path = self.conv.export_code()
            logger.info(f"Code exported: {down_path}")
            return [gr.Button(visible=False), gr.DownloadButton(label=f"Download Notebook", value=down_path, visible=True)]
        except Exception as e:
            logger.error(f"Error in export_code: {e}")
            return [gr.Button(visible=False), gr.DownloadButton(label=f"Error: {e}", visible=True)]

    def down_report(self):
        return [gr.Button(visible=True), gr.DownloadButton(visible=False)]

    def down_notebook(self):
        return [gr.Button(visible=True), gr.DownloadButton(visible=False)]

    def chat_streaming(self, message, chat_history, code=None):
        try:
            if not code:
                self.conv.programmer.messages.append({"role": "user", "content": message})
            else:
                message = code
            
            # Validate message
            if not message or not message.strip():
                logger.warning("Empty message received")
                return "", chat_history
            
            chat_history = chat_history + [
                {"role": "user", "content": message},
                {"role": "assistant", "content": ""}
            ]
            return "", chat_history
        except Exception as e:
            logger.error(f"Error in chat_streaming: {e}")
            return "", chat_history

    def save_dialogue(self, chat_history):
        try:
            self.conv.save_conv()
            save_path = os.path.join(self.session_cache_path, 'system_dialogue.json')
            with open(save_path, 'w', encoding='utf-8') as f:
                json.dump(chat_history, f, indent=4, ensure_ascii=False)
            logger.info(f"Dialogue saved in {save_path}")
        except Exception as e:
            logger.error(f"Error saving dialogue: {e}")
            raise

    def load_dialogue(self, dialogue_path):
        try:
            system_dialogue_path = os.path.join(dialogue_path, 'system_dialogue.json')
            system_config_path = os.path.join(dialogue_path, 'config.json')
            
            # Validate paths exist
            if not os.path.exists(system_dialogue_path):
                logger.warning(f"Dialogue file not found: {system_dialogue_path}")
                return []
            
            with open(system_dialogue_path, 'r', encoding='utf-8') as f:
                chat_history = json.load(f)
            
            with open(system_config_path, 'r', encoding='utf-8') as f:
                sys_config = json.load(f)
            
            self.session_cache_path = sys_config["session_cache_path"]
            self.config["session_cache_path"] = self.session_cache_path
            self.config["chat_history_display"] = chat_history
            self.config["figure_list"] = sys_config["figure_list"]
            
            logger.info(f"Dialogue loaded from {dialogue_path}")
            return chat_history
        except Exception as e:
            logger.error(f"Failed to load the chat history: {e}")
            return []

    def clear_all(self, message, chat_history):
        try:
            self.conv.clear()
            logger.info("All data cleared")
            return "", []
        except Exception as e:
            logger.error(f"Error in clear_all: {e}")
            return "", []

    def update_config(self, conv_model, programmer_model, inspector_model, api_key,
                      base_url_conv_model, base_url_programmer, base_url_inspector,
                      max_attempts, max_exe_time,
                      load_chat, chat_history_path):

        try:
            self.conv.update_config(conv_model=conv_model, programmer_model=programmer_model, inspector_model=inspector_model, api_key=api_key,
                          base_url_conv_model=base_url_conv_model, base_url_programmer=base_url_programmer, base_url_inspector=base_url_inspector,
                          max_attempts=max_attempts, max_exe_time=max_exe_time)

            if load_chat == True:
                self.config['chat_history_path'] = chat_history_path
                chat_history = self.load_dialogue(chat_history_path)
                self.config['load_chat'] = load_chat
                logger.info("Config updated successfully")
                return ["### Config Updated!", chat_history]

            logger.info("Config updated successfully")
            return "### Config Updated!", []
        except Exception as e:
            logger.error(f"Error in update_config: {e}")
            return "### Config Update Failed!", []

    def get_performance_metrics(self):
        """Returns performance metrics for the Polyglot Benchmark."""
        return {
            "evolution_params": self.get_evolution_params(),
            "session_cache_path": self.session_cache_path,
            "file_count": len(self.conv.file_list),
            "message_count": len(self.conv.programmer.messages),
            "timestamp": datetime.now().isoformat()
        }

    def generate_config_data(self, num_entries=20):
        """Generate config entries for Polyglot Benchmark testing."""
        try:
            models = ['gpt-4', 'gpt-3.5-turbo', 'claude-2', 'llama-2-70b', 'mistral-7b']
            urls = [
                'https://api.openai.com/v1/chat/completions',
                'https://api.anthropic.com/v1/messages',
                'https://api.mistral.ai/v1/chat/completions',
                'http://localhost:8000/v1/chat/completions',
                'https://api.deepai.org/v1/chat'
            ]
            
            generated_configs = []
            for i in range(num_entries):
                config = {
                    'model': random.choice(models),
                    'url': random.choice(urls),
                    'tokens': random.randint(100, 5000),
                    'temp': round(random.uniform(0.1, 1.5), 2),
                    'key': ''.join(random.choices('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=random.randint(20, 40)))
                }
                generated_configs.append(config)
            
            logger.info(f"Generated {num_entries} config entries")
            return generated_configs
        except Exception as e:
            logger.error(f"Error in generate_config_data: {e}")
            return []

    def analyze_config_data(self, config_data):
        """Analyze config data for cost_score, localhost, and key length."""
        try:
            if not config_data:
                return {"error": "No config data provided"}
            
            df = pd.DataFrame(config_data)
            
            # Calculate cost_score
            df['cost_score'] = df['tokens'] * df['temp']
            
            # Average cost_score per model
            avg_cost_per_model = df.groupby('model')['cost_score'].mean().reset_index()
            avg_cost_per_model.columns = ['model', 'avg_cost_score']
            
            # Flag localhost in prod
            localhost_flag = df[df['url'].str.contains('localhost', case=False, na=False)]
            localhost_entries = len(localhost_flag)
            
            # Flag keys <32 chars
            key_length_flag = df[df['key'].str.len() < 32]
            short_key_entries = len(key_length_flag)
            
            analysis_result = {
                'avg_cost_per_model': avg_cost_per_model.to_dict('records'),
                'localhost_entries': localhost_entries,
                'short_key_entries': short_key_entries,
                'total_entries': len(df),
                'df_summary': df.describe().to_dict()
            }
            
            logger.info(f"Analysis completed - localhost: {localhost_entries}, short keys: {short_key_entries}")
            return analysis_result
        except Exception as e:
            logger.error(f"Error in analyze_config_data: {e}")
            return {"error": str(e)}

    def generate_analysis_code(self, config_data):
        """Generate Python code for config generation and analysis."""
        code_template = '''
import pandas as pd
import numpy as np
import random
import re

def generate_config_data(num_entries=20):
    """Generate config entries for testing."""
    models = ['gpt-4', 'gpt-3.5-turbo', 'claude-2', 'llama-2-70b', 'mistral-7b']
    urls = [
        'https://api.openai.com/v1/chat/completions',
        'https://api.anthropic.com/v1/messages',
        'https://api.mistral.ai/v1/chat/completions',
        'http://localhost:8000/v1/chat/completions',
        'https://api.deepai.org/v1/chat'
    ]
    
    generated_configs = []
    for i in range(num_entries):
        config = {{
            'model': random.choice(models),
            'url': random.choice(urls),
            'tokens': random.randint(100, 5000),
            'temp': round(random.uniform(0.1, 1.5), 2),
            'key': ''.join(random.choices('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=random.randint(20, 40)))
        }}
        generated_configs.append(config)
    
    return generated_configs

def analyze_config_data(config_data):
    """Analyze config data for cost_score, localhost, and key length."""
    df = pd.DataFrame(config_data)
    
    # Calculate cost_score
    df['cost_score'] = df['tokens'] * df['temp']
    
    # Average cost_score per model
    avg_cost_per_model = df.groupby('model')['cost_score'].mean().reset_index()
    
    # Flag localhost in prod
    localhost_flag = df[df['url'].str.contains('localhost', case=False, na=False)]
    
    # Flag keys <32 chars
    key_length_flag = df[df['key'].str.len() < 32]
    
    analysis_result = {{
        'avg_cost_per_model': avg_cost_per_model,
        'localhost_entries': len(localhost_flag),
        'short_key_entries': len(key_length_flag),
        'total_entries': len(df)
    }}
    
    return analysis_result

# Example usage
if __name__ == "__main__":
    config_data = generate_config_data(20)
    analysis = analyze_config_data(config_data)
    print("Average cost per model:")
    print(analysis['avg_cost_per_model'])
    print(f"\\nLocalhost entries: {{analysis['localhost_entries']}}")
    print(f"Short key entries: {{analysis['short_key_entries']}}")
'''
        return code_template