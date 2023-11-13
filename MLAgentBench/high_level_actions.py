""" This file contains high level actions that may contain multiple low level actions and LLM calls. """

import os
import datetime
import shutil
import difflib
from .low_level_actions import read_file, write_file, append_file
from .schema import ActionInfo, EnvException
from .LLM import complete_text_fast, complete_text

import re
import json
import time
from duckduckgo_search import DDGS
from itertools import islice
from pprint import pprint
from selenium.webdriver.chrome.webdriver import WebDriver as ChromeDriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup

def reflection( things_to_reflect_on, work_dir = ".", research_problem = "", **kwargs):

    research_log_content = read_file("research_log.log", work_dir = work_dir,  **kwargs)

    prompt = f"""We are trying to solve this research problem: {research_problem}
    Your current research log:
    ```
    {research_log_content}
    ```
    Reflect on this: {things_to_reflect_on} 
    Give an answer in natural language paragraphs as truthfully as possible. 
    """
    reflection = complete_text_fast(prompt, log_file=kwargs["log_file"])
    return f"Reflection: {reflection}\n"


def understand_file( file_name, things_to_look_for, work_dir = ".", **kwargs):

    lines = read_file(file_name, work_dir = work_dir, **kwargs).split("\n")
    # group lines to blocks so that each block has at most 10000 characters
    counter = 0
    blocks = []
    while counter < len(lines):
        block = []
        start_line_number = counter + 1
        while counter < len(lines) and len("\n".join(block)) + len(lines[counter]) < 10000:
            block.append(lines[counter])
            counter += 1
        if len(block) > 0:
            end_line_number = counter 
            blocks.append(("\n".join(block), start_line_number, end_line_number))
        else:
            end_line_number = start_line_number
            # probably a file of one/few very long line; split by 10000 characters
            for i in range(0, len(lines[counter]), 10000):
                blocks.append((lines[counter][i:i+10000], start_line_number, end_line_number))
            counter += 1

    descriptions  = []
    for idx, (b, start_line_number, end_line_number) in enumerate(blocks):
        start_char_number = sum([len(b) for b in blocks[:idx]])
        end_char_number = start_line_number + len(b)
        prompt = f"""Given this (partial) file from line {start_line_number} character {start_char_number} to line {end_line_number} character {end_char_number}: 
    ``` 
    {b}
    ```
    Here is a detailed description on what to look for and what should returned: {things_to_look_for}
    The description should short and also reference crtical lines in the script relevant to what is being looked for. Only describe what is objectively confirmed by the file content. Do not include guessed numbers. If you cannot find the answer to certain parts of the request, you should say "In this segment, I cannot find ...".
    """

        completion = complete_text_fast(prompt, log_file=kwargs["log_file"]+f"_{idx}")
        descriptions.append(completion)
    if len(descriptions) == 1:
        return descriptions[0]
    else:
        descriptions = "\n\n".join(["Segment {idx}: \n\n" + s for s in descriptions])
        prompt = f"""Given the relevant observations for each segments of a file, summarize to get a cohesive description of the entire file on what to look for and what should returned: {things_to_look_for}
    {descriptions}
    """

        completion = complete_text_fast(prompt, log_file=kwargs["log_file"])

        return completion

EDIT_SCRIPT_MODEL = "claude-v1"
EDIT_SCRIPT_MAX_TOKENS = 4000
def edit_script(script_name, edit_instruction, save_name, work_dir = ".", **kwargs):
    #TODO: handle long file editing
    try:
        content = read_file(script_name, work_dir = work_dir, **kwargs)
    except:
        write_file(script_name, "", work_dir = work_dir, **kwargs)
        content = ""
        
    prompt = f"""Given this python script:
    ```python 
    {content}
    ```
    Edit the script by following the instruction:
    {edit_instruction}
    Provide the full code after the edit, making no other changes. Start the python code with "```python". 

    """

    completion = complete_text(prompt, log_file=kwargs["log_file"], model=EDIT_SCRIPT_MODEL, max_tokens_to_sample=EDIT_SCRIPT_MAX_TOKENS)

    new_content = completion.split("```python")[1].split("```")[0].strip()

    # backup all old file with prefix script_name
    backup_name = os.path.join(work_dir,"backup", f"{script_name}_{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}")
    shutil.copyfile(os.path.join(work_dir,script_name), backup_name)

    write_file(save_name, new_content, work_dir = work_dir, **kwargs)

    diff = list(difflib.unified_diff(content.splitlines(keepends=True), new_content.splitlines(keepends=True)))
    diff = "".join(diff)

    return f"The edited file is saved to {save_name}. Here is the diff, please check if the edit is correct and desirable:\n\n" + diff


def append_to_research_log( content, work_dir = ".", **kwargs):
    append_file("research_log.log", content+"\n", work_dir = work_dir, **kwargs)

    return "Successfully appended to research log"

def edit_script_lines( script_name, start_line_number, end_line_number,edit_instruction, save_name, work_dir = ".", **kwargs):
    try:
        start_line_number = int(start_line_number)
        end_line_number = int(end_line_number)
    except:
        raise EnvException("start_line_number and end_line_number must be integers")
    
    try:
        orig_content = read_file(script_name, work_dir = work_dir, **kwargs)
    except:
        write_file(script_name, "", work_dir = work_dir, **kwargs)
        orig_content = ""
    lines = orig_content.split("\n")
    content = "\n".join(lines[max(int(start_line_number)-1, 0):int(end_line_number)])
        
    prompt = f"""Given this segment of a python script:
    ```python 
    {content}
    ```
    Edit this segemnt by following the instruction:
    {edit_instruction}
    Provide the full code after the edit, making no other changes. Start the python code with "```python". 

    """

    completion = complete_text(prompt, log_file=kwargs["log_file"], model=EDIT_SCRIPT_MODEL, max_tokens_to_sample=EDIT_SCRIPT_MAX_TOKENS)

    new_content = "\n".join(lines[:int(start_line_number)-1]) + "\n" + completion.split("```python")[1].split("```")[0].strip() + "\n" + "\n".join(lines[int(end_line_number):])

    # backup all old file with prefix script_name
    backup_name = os.path.join(work_dir,"backup", f"{script_name}_{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}")
    shutil.copyfile(os.path.join(work_dir,script_name), backup_name)

    write_file(save_name, new_content, work_dir = work_dir, **kwargs)

    diff = list(difflib.unified_diff(content.splitlines(keepends=True), new_content.splitlines(keepends=True)))
    diff = "".join(diff)

    return f"The edited file is saved to {save_name}. Here is the diff, please check if the edit is correct and desirable:\n\n" + diff


def inspect_script_lines( script_name, start_line_number, end_line_number, work_dir = ".", **kwargs):
    try:
        start_line_number = int(start_line_number)
        end_line_number = int(end_line_number)
    except:
        raise EnvException("start_line_number and end_line_number must be integers")
    if end_line_number - start_line_number > 100:
        raise EnvException("the number of lines to display is limited to 100 lines")
    try:
        
        # lines = open(os.path.join(work_dir,script_name)).readlines()
        lines = read_file(script_name, work_dir = work_dir, **kwargs).split("\n")
    except:
        raise EnvException(f"cannot find script {script_name}")

    content = "\n".join(lines[max(int(start_line_number)-1, 0):int(end_line_number)])
    return f"Here are the lines (the file ends at line {len(lines)}):\n\n" + content

def retrieval_from_research_log(current_plan, work_dir = ".", **kwargs):

    research_problem = kwargs["research_problem"]

    research_log_content = read_file("research_log.log", work_dir = work_dir, **kwargs)
    
    prompt = f"""We are trying to solve this research problem: {research_problem}
Your current Research Plan and Status
{current_plan}
    
Your current research log:
```
{research_log_content}
```
Concisely summarize and list all relevant information from the research log that will be helpful for future step in this format:
"""

    retrieval = complete_text_fast(prompt, log_file=kwargs["log_file"])

    return retrieval

def search_the_web(search_query, number_of_results):
    try:
        number_of_results = int(number_of_results)
    except:
        raise EnvException("number_of_results must be an integer")

    search_results = []
    attempts = 0

    while attempts < DUCKDUCKGO_MAX_ATTEMPTS:
        if not search_query:
            return json.dumps(search_results)

        results = DDGS().text(search_query)
        search_results = list([res["href"] for res in islice(results, number_of_results)])

        if search_results:
            break

        time.sleep(1)
        attempts += 1

    test_search_results = [scrape_text_with_selenium_no_agent(url) for url in search_results]
    json_results = json.dumps(test_search_results, ensure_ascii=False, indent=4)

    if isinstance(json_results, list):
        safe_message = json.dumps(
            [result.encode("utf-8", "ignore").decode("utf-8") for result in results]
        )
    else:
        safe_message = json_results.encode("utf-8", "ignore").decode("utf-8")
    return safe_message
    
def scrape_text_with_selenium_no_agent(url: str) -> str:
    driver = ChromeDriver()
    driver.set_page_load_timeout(15)
    driver.implicitly_wait(15)
    print("set timeout!")

    try:
        driver.get(url)
    except TimeoutException:
        print('Page did not load within 15 seconds')
        return "No information found"
    except Exception as e:
        print('An unexpected error occurred')
        return "No information found"
    except: 
        print('there was an error')

    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.TAG_NAME, "body"))
    )

    # Get the HTML content directly from the browser's DOM
    page_source = driver.execute_script("return document.body.outerHTML;")
    soup = BeautifulSoup(page_source, "html.parser")

    for script in soup(['style', 'script', 'head', 'title', 'meta', '[document]', 'header', 'footer', 'iframe']):
        script.extract()

    text = soup.get_text()
    lines = (line.strip() for line in text.splitlines())
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    text = "\n".join(chunk for chunk in chunks if chunk)

    text = text[:300] #TODO shitty truncation processing...

    driver.quit()

    return text


HIGH_LEVEL_ACTIONS =[
    ActionInfo(
        name="Understand File",
        description="Use this to read the whole file and understand certain aspects. You should provide detailed description on what to look for and what should be returned. To get a better understanding of the file, you can use Inspect Script Lines action to inspect specific part of the file.",
        usage={
            "file_name": "a valid file name with relative path to current directory if needed",
            "things_to_look_for": "a detailed description on what to look for and what should returned"
        },
        return_value="The observation will be a description of relevant content and lines in the file. If the file does not exist, the observation will be an error message.",
        function=understand_file
    ),
    ActionInfo(
        name="Append Summary to Research Log",
        description="Append to the summary of previous step to research log",
        usage={
            "content": "a string within 500 character limit"
        },
        return_value="The observation will be a success message if the content is appended to the research log. Otherwise, the observation will be an error message.",
        function=append_to_research_log
    ),
    ActionInfo(
        name="Inspect Script Lines",
        description="Use this to inspect specific part of a python script precisely, or the full content of a short script. The number of lines to display is limited to 100 lines. This is especially helpful when debugging.",
        usage={
            "script_name": "a valid python script name with relative path to current directory if needed",
            "start_line_number": "a valid line number",
            "end_line_number": "a valid line number"
        },
        return_value="The observation will be the content of the script between start_line_number and end_line_number . If the script does not exist, the observation will be an error message.",
        function=inspect_script_lines
    ),
    ActionInfo(
        name="Edit Script (AI)",
        description="Use this to do a relatively large but cohesive edit over a python script. Instead of editing the script directly, you should describe the edit instruction so that another AI can help you do this.",
        usage={
            "script_name": "a valid python script name with relative path to current directory if needed. An empty sctipt will be created if it does not exist.",
            "edit_instruction": "a detailed step by step description on how to edit it.",
            "save_name": "a valid file name with relative path to current directory if needed"
        },
        return_value="The observation will be the edited content of the script. If the script does not exist, the observation will be an error message. You should always double check whether the edit is correct. If it is far from correct, you can use the Undo Edit Script action to undo the edit.",
        function=edit_script
    ),
    ActionInfo(
        name="Edit Script Segment (AI)",
        description="Use this to do a relatively large but cohesive edit over a python script over a segment. Instead of editing the script directly, you should describe the edit instruction so that another AI can help you do this.",
        usage={
            "script_name": "a valid python script name with relative path to current directory if needed. An empty sctipt will be created if it does not exist.",
            "start_line_number": "a valid line number",
            "end_line_number": "a valid line number",
            "edit_instruction": "a detailed step by step description on how to edit it.",
            "save_name": "a valid file name with relative path to current directory if needed"
        },
        return_value="The observation will be the edited content of the script. If the script does not exist, the observation will be an error message. You should always double check whether the edit is correct. If it is far from correct, you can use the Undo Edit Script action to undo the edit.",
        function=edit_script_lines
    ),
    ActionInfo(
        name="Reflection",
        description="Use this to look over all the past steps and reflect. You should provide detailed description on what to reflect on and what should be returned.",
        usage={
            "things_to_reflect_on": "a detailed description on what to reflect on and what should be returned"
        },
        return_value="The observation will be a the reflection.",
        function=reflection
    ),
    ActionInfo(
        name="Retrieval from Research Log",
        description="Use this to retrieve relevant information from the research log. You should provide detailed description on what to look for and what should be returned.",
        usage={
            "current_plan": "a detailed description of the current research plan and status",
        },
        return_value="The observation will be a description of relevant content and lines in the research log.",
        function=retrieval_from_research_log
    ),
    ActionInfo(
        name="Search the Internet",
        description="Use this to search the Internet for relevant information that may help with the task. You should provide a search query and number of results; the function will then perform a web search and return the text content of the top n results, where n is the number of results you specified.",
        usage={
            "search_query": "a short description of what you want to search the Internet for",
            "number_of_results": "a small positive number, for the number of webpages to see results from via this Internet search"
        },
        return_value="The observation will be the text bodies of the webpages returned in the Internet search.",
        function=search_the_web
    )
]
