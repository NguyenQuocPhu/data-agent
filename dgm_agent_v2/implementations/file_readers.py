import json
import zlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd


@dataclass
class FileContext:
    """Context read from a single file."""
    file_path: str
    file_type: str
    columns: List[str] = field(default_factory=list)
    dtypes: Dict[str, str] = field(default_factory=dict)
    sheets: List[str] = field(default_factory=list)
    preview: str = ""
    error: Optional[str] = None


class IFileReader(ABC):
    """Interface for file reader strategies."""
    
    def _compute_ncd(self, x: bytes, y: bytes) -> float:
        if not x and not y:
            return 0.0
        if not x or not y:
            return 1.0
        cx = len(zlib.compress(x))
        cy = len(zlib.compress(y))
        cxy = len(zlib.compress(x + b' ' + y))
        return (cxy - min(cx, cy)) / max(cx, cy)

    def _prune_dataframe(self, df: pd.DataFrame, goal_hint: str) -> str:
        if df.empty or not goal_hint:
            return df.head(20).to_string(index=False, max_rows=20, max_cols=15)
        
        goal_bytes = goal_hint.encode('utf-8')
        scored_rows = []
        df_limited = df.head(1000)
        columns = df_limited.columns.tolist()
        
        for _, row in df_limited.iterrows():
            row_str = ", ".join(f"{c}: {v}" for c, v in zip(columns, row.values))
            score = self._compute_ncd(goal_bytes, row_str.encode('utf-8'))
            scored_rows.append((score, row_str))
            
        scored_rows.sort(key=lambda x: x[0])
        return "\n".join(x[1] for x in scored_rows[:20])

    def _prune_text(self, lines: List[str], goal_hint: str) -> str:
        if not lines or not goal_hint:
            return "".join(lines[:20])[:2000]
            
        goal_bytes = goal_hint.encode('utf-8')
        scored_lines = []
        
        for line in lines[:1000]:
            line_str = line.strip()
            if not line_str: continue
            score = self._compute_ncd(goal_bytes, line_str.encode('utf-8'))
            scored_lines.append((score, line_str))
            
        scored_lines.sort(key=lambda x: x[0])
        return "\n".join(x[1] for x in scored_lines[:20])[:2000]

    @abstractmethod
    def read(self, fpath: str, goal_hint: str) -> FileContext:
        pass


class CsvReader(IFileReader):
    def read(self, fpath: str, goal_hint: str) -> FileContext:
        try:
            df = pd.read_csv(fpath, nrows=1000, encoding="utf-8", on_bad_lines="skip")
            return FileContext(
                file_path=fpath,
                file_type="csv",
                columns=list(df.columns),
                dtypes={col: str(df[col].dtype) for col in df.columns},
                preview=self._prune_dataframe(df, goal_hint),
            )
        except Exception as e:
            return FileContext(file_path=fpath, file_type="csv", error=str(e))


class ExcelReader(IFileReader):
    def read(self, fpath: str, goal_hint: str) -> FileContext:
        try:
            xl = pd.ExcelFile(fpath)
            sheets = xl.sheet_names
            df = pd.read_excel(fpath, sheet_name=sheets[0], nrows=1000)
            return FileContext(
                file_path=fpath,
                file_type="xlsx",
                columns=list(df.columns),
                dtypes={col: str(df[col].dtype) for col in df.columns},
                sheets=sheets,
                preview=self._prune_dataframe(df, goal_hint),
            )
        except Exception as e:
            return FileContext(file_path=fpath, file_type="xlsx", error=str(e))


class JsonReader(IFileReader):
    def read(self, fpath: str, goal_hint: str) -> FileContext:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                lines = f.readlines()
            preview = self._prune_text(lines, goal_hint)
            
            try:
                obj = json.loads("".join(lines))
                cols = list(obj[0].keys()) if isinstance(obj, list) and obj and isinstance(obj[0], dict) else []
            except Exception:
                cols = []
                
            return FileContext(file_path=fpath, file_type="json", columns=cols, preview=preview)
        except Exception as e:
            return FileContext(file_path=fpath, file_type="json", error=str(e))


class GenericReader(IFileReader):
    def read(self, fpath: str, goal_hint: str) -> FileContext:
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            return FileContext(
                file_path=fpath, 
                file_type="txt", 
                preview=self._prune_text(lines, goal_hint)
            )
        except Exception as e:
            return FileContext(file_path=fpath, file_type="other", error=str(e))


class FileReaderFactory:
    """Factory to get the right strategy based on file extension."""
    @staticmethod
    def get_reader(fpath: str) -> IFileReader:
        ext = Path(fpath).suffix.lower()
        if ext == ".csv":
            return CsvReader()
        elif ext in (".xlsx", ".xls", ".ods"):
            return ExcelReader()
        elif ext == ".json":
            return JsonReader()
        else:
            return GenericReader()
