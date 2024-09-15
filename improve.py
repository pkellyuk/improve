import tkinter as tk
from tkinter import scrolledtext, ttk, simpledialog
import requests
import json
import threading
import queue
import re
import subprocess
import os
import tempfile
import sys
import asyncio
import traceback
import importlib

class CodeExecutionWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Code Execution Log")
        self.geometry("600x400")

        self.text_area = scrolledtext.ScrolledText(self, wrap=tk.WORD, width=70, height=20)
        self.text_area.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

    def log(self, message):
        self.text_area.insert(tk.END, message + "\n")
        self.text_area.see(tk.END)
        print(f"Log: {message}")  # Print to console as well

class UserCriticismDialog(simpledialog.Dialog):
    def __init__(self, parent, title, last_response):
        self.last_response = last_response
        super().__init__(parent, title)

    def body(self, master):
        ttk.Label(master, text="Last Response:").grid(row=0, column=0, sticky="w", pady=(0, 5))
        last_response_text = scrolledtext.ScrolledText(master, wrap=tk.WORD, width=60, height=10)
        last_response_text.grid(row=1, column=0, pady=(0, 10))
        last_response_text.insert(tk.END, self.last_response)
        last_response_text.config(state=tk.DISABLED)

        ttk.Label(master, text="Your Criticism:").grid(row=2, column=0, sticky="w", pady=(0, 5))
        self.criticism_text = scrolledtext.ScrolledText(master, wrap=tk.WORD, width=60, height=10)
        self.criticism_text.grid(row=3, column=0)
        return self.criticism_text

    def apply(self):
        self.result = self.criticism_text.get("1.0", tk.END).strip()

class OllamaIterativeImprovementGUI:
    def __init__(self, master):
        self.master = master
        master.title("Ollama Iterative Improvement")
        master.geometry("800x700")

        # Query input
        self.query_label = tk.Label(master, text="Enter your query:")
        self.query_label.pack(pady=(10, 0))
        self.query_entry = tk.Entry(master, width=70)
        self.query_entry.pack(pady=(0, 10))
        self.query_entry.bind('<Return>', self.start_query)

        # Iteration slider
        self.iteration_label = tk.Label(master, text="Number of iterations:")
        self.iteration_label.pack()
        self.iteration_slider = tk.Scale(master, from_=1, to=100, orient=tk.HORIZONTAL, length=200)
        self.iteration_slider.set(5)  # Default to 5 iterations
        self.iteration_slider.pack()

        # Submit button
        self.submit_button = tk.Button(master, text="Submit", command=self.start_query)
        self.submit_button.pack(pady=(0, 10))

        # Response text area
        self.response_text = scrolledtext.ScrolledText(master, wrap=tk.WORD, width=80, height=30)
        self.response_text.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)
        self.response_text.insert(tk.END, "Responses will appear here.")

        # Progress bar
        self.progress = ttk.Progressbar(master, orient=tk.HORIZONTAL, length=300, mode='determinate')
        self.progress.pack(pady=10)

        # Code execution window button
        self.code_window_button = tk.Button(master, text="Show Code Execution Log", command=self.toggle_code_window)
        self.code_window_button.pack(pady=10)

        # Code execution window (create it at startup)
        self.code_window = CodeExecutionWindow(self.master)
        self.code_window.withdraw()  # Hide it initially

        # Queue for thread-safe GUI updates
        self.queue = queue.Queue()
        self.master.after(100, self.process_queue)

        # Create an event loop for asynchronous tasks
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.thread = threading.Thread(target=self.run_async_loop, daemon=True)
        self.thread.start()

        # Event for synchronizing user criticism dialog
        self.criticism_event = threading.Event()
        self.user_criticism = ""

    def run_async_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def toggle_code_window(self):
        if self.code_window.winfo_viewable():
            self.code_window.withdraw()
            self.code_window_button.config(text="Show Code Execution Log")
        else:
            self.code_window.deiconify()
            self.code_window_button.config(text="Hide Code Execution Log")

    def start_query(self, event=None):
        query = self.query_entry.get()
        iterations = self.iteration_slider.get()
        if query:
            self.response_text.delete('1.0', tk.END)
            self.progress['value'] = 0
            self.code_window.text_area.delete('1.0', tk.END)
            threading.Thread(target=self.query_model_iteratively, args=(query, iterations), daemon=True).start()

    def get_user_criticism(self, iteration, last_response):
        def show_dialog():
            dialog = UserCriticismDialog(self.master, f"Criticism for Iteration {iteration}", last_response)
            self.user_criticism = dialog.result if dialog.result else "No criticism provided."
            self.criticism_event.set()

        self.master.after(0, show_dialog)
        self.criticism_event.wait()
        self.criticism_event.clear()
        return self.user_criticism

    def query_model_iteratively(self, query, iterations):
        try:
            model = "gemma2:27b"
            last_response = ""
            execution_log = ""

            for i in range(iterations):
                if i > 0:
                    # Get user criticism
                    user_criticism = self.get_user_criticism(i, last_response)
                else:
                    user_criticism = ""

                if i == 0:
                    prompt = query
                else:
                    prompt = f"""This was the original query: '{query}'

Your last response was:
{last_response}

Here is the log of executing the code in your last response:
{execution_log}

User criticism of your last response:
{user_criticism}

Please improve on your previous response, taking into account the execution results and user criticism. If there were any errors or criticisms, address them in your response."""

                self.queue.put(("update_text", f"\n--- Iteration {i+1}/{iterations} ---\n"))
                self.queue.put(("log", f"Sending prompt to model: {prompt[:100]}..."))
                response = self.query_model_stream(model, prompt)
                last_response = response

                self.queue.put(("log", f"Received response: {response[:100]}..."))

                # Extract and execute Python code
                code_blocks = re.findall(r'```python\n(.*?)\n```', response, re.DOTALL)
                self.queue.put(("log", f"Found {len(code_blocks)} code blocks"))
                
                execution_log = ""
                if code_blocks:
                    for idx, code in enumerate(code_blocks):
                        self.queue.put(("log", f"Executing code block {idx + 1}:"))
                        self.queue.put(("log", code))
                        future = asyncio.run_coroutine_threadsafe(self.execute_code(code), self.loop)
                        result = future.result()  # Wait for the code execution to complete
                        execution_log += f"Code Block {idx + 1} Execution Log:\n{result}\n\n"

                self.queue.put(("update_progress", (i + 1) / iterations * 100))

            self.queue.put(("update_text", "\nProcess complete."))
        except Exception as e:
            self.queue.put(("log", f"Error in query_model_iteratively: {str(e)}"))
            self.queue.put(("log", traceback.format_exc()))

    def query_model_stream(self, model, prompt):
        url = "http://localhost:11434/api/generate"
        data = {
            "model": model,
            "prompt": prompt,
            "stream": True
        }
        
        try:
            response = requests.post(url, json=data, stream=True)
            if response.status_code == 200:
                full_response = ""
                for line in response.iter_lines():
                    if line:
                        chunk = json.loads(line)
                        if 'response' in chunk:
                            self.queue.put(("update_text", chunk['response']))
                            full_response += chunk['response']
                        if chunk.get('done', False):
                            break
                return full_response
            else:
                error_msg = f"Error: HTTP {response.status_code}"
                self.queue.put(("log", error_msg))
                return error_msg
        except requests.RequestException as e:
            error_msg = f"Request failed: {str(e)}"
            self.queue.put(("log", error_msg))
            return error_msg

    async def execute_code(self, code):
        self.queue.put(("log", "Starting code execution..."))
        self.queue.put(("log", f"Code to execute:\n{code}"))

        execution_log = "Starting code execution...\n"
        try:
            # Create a temporary directory
            with tempfile.TemporaryDirectory() as tmpdir:
                # Save the code to a temporary file
                file_path = os.path.join(tmpdir, "temp_code.py")
                with open(file_path, "w") as f:
                    f.write(code)

                execution_log += f"Saved code to temporary file: {file_path}\n"

                # Extract required packages
                packages = re.findall(r'import (\w+)', code)
                packages.extend(re.findall(r'from (\w+)', code))

                # Install or check required packages
                for package in packages:
                    if package not in sys.modules:
                        try:
                            importlib.import_module(package)
                            execution_log += f"Package {package} is already available.\n"
                        except ImportError:
                            execution_log += f"Attempting to install package: {package}\n"
                            try:
                                await self.install_package(package)
                            except Exception as e:
                                execution_log += f"Failed to install {package}: {str(e)}. Continuing execution.\n"

                # Execute the code
                execution_log += "Executing code...\n"
                result = await self.run_python_script(file_path)
                execution_log += f"Code Execution Result:\n{result}\n"
                self.queue.put(("update_text", f"\nCode Execution Result:\n{result}\n"))

        except Exception as e:
            error_msg = f"Error executing code: {str(e)}"
            execution_log += f"{error_msg}\n"
            execution_log += traceback.format_exc()
            self.queue.put(("update_text", f"\n{error_msg}\n"))

        self.queue.put(("log", execution_log))
        return execution_log

    async def install_package(self, package):
        self.queue.put(("log", f"Running: pip install {package}"))
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pip", "install", package,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise Exception(f"Failed to install {package}: {stderr.decode()}")
        else:
            self.queue.put(("log", f"Successfully installed {package}"))

    async def run_python_script(self, file_path):
        self.queue.put(("log", f"Running: python {file_path}"))
        process = await asyncio.create_subprocess_exec(
            sys.executable, file_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            self.queue.put(("log", f"Script execution failed: {stderr.decode()}"))
            raise Exception(f"Script execution failed: {stderr.decode()}")
        self.queue.put(("log", "Script executed successfully"))
        return stdout.decode()

    def process_queue(self):
        try:
            while True:
                method, arg = self.queue.get_nowait()
                if method == "update_text":
                    self.response_text.insert(tk.END, arg)
                    self.response_text.see(tk.END)
                elif method == "update_progress":
                    self.progress['value'] = arg
                elif method == "log":
                    self.code_window.log(arg)
        except queue.Empty:
            pass
        self.master.after(100, self.process_queue)

if __name__ == "__main__":
    root = tk.Tk()
    app = OllamaIterativeImprovementGUI(root)
    root.mainloop()