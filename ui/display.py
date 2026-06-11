import gradio
import html
import re

def display_text(text):
    return f"\n\n{text}\n\n"

def display_image(path):
    return f"\n\n![Chart](/file?path={path})\n\n"


def display_exe_results(text):
    return f"\n\n**Execution Results:**\n```trace\n{text}\n```\n\n"


def display_download_file(path, filename):
    return f"\n\n**Download:** [{filename}](/file?path={path})\n\n"

def suggestion_html(suggestions: list) -> str:
    buttons_html = ""
    for suggestion in suggestions:
        buttons_html += f"""<button class='suggestion-btn'>{suggestion}</button>"""
    return f"<div>{buttons_html}</div>"


def display_suggestions(prog_response, chat_history_display_last):
    '''
        replace HTML buttons with clean markdown lists so Next.js can render it properly.
    '''
    suggest_list = re.findall(r'\[\d+\]\s*(.*)', prog_response)
    if suggest_list:
        markdown_list = "\n".join([f"- **Option {i+1}:** {sugg}" for i, sugg in enumerate(suggest_list)])
        
        pattern = r'(Next, you can:)(.*?)(?=(?:<br>)?\Z)'
        chat_history_display_last = re.sub(pattern, r'\1\n\n' + markdown_list, chat_history_display_last, flags=re.DOTALL)

    return chat_history_display_last
