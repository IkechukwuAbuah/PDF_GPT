import urllib.request
import fitz
import re
import numpy as np
import tensorflow_hub as hub
import openai
import gradio as gr
import os
from sklearn.neighbors import NearestNeighbors

# Function to download a PDF from a given URL and save it to a specified output path
def download_pdf(url, output_path):
    urllib.request.urlretrieve(url, output_path)

# Function to preprocess text by removing newline characters and multiple spaces
def preprocess(text):
    text = text.replace('\n', ' ')
    text = re.sub('\s+', ' ', text)
    return text

# Function to extract text from a PDF file
def pdf_to_text(path, start_page=1, end_page=None):
    doc = fitz.open(path)
    total_pages = doc.page_count

    if end_page is None:
        end_page = total_pages

    text_list = []

    for i in range(start_page-1, end_page):
        text = doc.load_page(i).get_text("text")
        text = preprocess(text)
        text_list.append(text)

    doc.close()
    return text_list

# Function to split the text into chunks with a specified word length
def text_to_chunks(texts, word_length=150, start_page=1):
    text_toks = [t.split(' ') for t in texts]
    page_nums = []
    chunks = []

    for idx, words in enumerate(text_toks):
        for i in range(0, len(words), word_length):
            chunk = words[i:i+word_length]
            if (i+word_length) > len(words) and (len(chunk) < word_length) and (
                len(text_toks) != (idx+1)):
                text_toks[idx+1] = chunk + text_toks[idx+1]
                continue
            chunk = ' '.join(chunk).strip()
            chunk = f'[{idx+start_page}]' + ' ' + '"' + chunk + '"'
            chunks.append(chunk)
    return chunks

# Class for performing semantic search using the Universal Sentence Encoder model
class SemanticSearch:
    
    def __init__(self):
        self.use = hub.load('https://tfhub.dev/google/universal-sentence-encoder/4')
        self.fitted = False

    def fit(self, data, batch=1000, n_neighbors=5):
        self.data = data
        self.embeddings = self.get_text_embedding(data, batch=batch)
        n_neighbors = min(n_neighbors, len(self.embeddings))
        self.nn = NearestNeighbors(n_neighbors=n_neighbors)
        self.nn.fit(self.embeddings)
        self.fitted = True

    def __call__(self, text, return_data=True):
        inp_emb = self.use([text])
        neighbors = self.nn.kneighbors(inp_emb, return_distance=False)[0]

        if return_data:
            return [self.data[i] for i in neighbors]
        else:
            return neighbors

    def get_text_embedding(self, texts, batch=1000):
        embeddings = []
        for i in range(0, len(texts), batch):
            text_batch = texts[i:(i+batch)]
            emb_batch = self.use(text_batch)
            embeddings.append(emb_batch)
        embeddings = np.vstack(embeddings)
        return embeddings

recommender = SemanticSearch()

# Function to load the recommender with text from a PDF file
def load_recommender(path, start_page=1):
    global recommender
    texts = pdf_to_text(path, start_page=start_page)
    chunks = text_to_chunks(texts, start_page=start_page)
    recommender.fit(chunks)
    return 'Corpus Loaded.'

# Function to generate text using GPT-3
def generate_text(prompt, engine="text-davinci-003"):
    completions = openai.Completion.create(
        engine=engine,
        prompt=prompt,
        max_tokens=512,
        n=1,
        stop=None,
        temperature=0.7,
    )
    message = completions.choices[0].text
    return message

# Function to generate an answer for a given question
def generate_answer(question):
    topn_chunks = recommender(question)
    prompt = ""
    prompt += 'search results:\n\n'
    for c in topn_chunks:
        prompt += c + '\n\n'
        
    prompt += "Instructions: Compose a comprehensive reply to the query using the search results given. "\
              "Cite each reference using [number] notation (every result has this number at the beginning). "\
              "Citation should be done at the end of each sentence. If the search results mention multiple subjects "\
              "with the same name, create separate answers for each. Only include information found in the results and "\
              "don't add any additional information. Make sure the answer is correct and don't output false content. "\
              "If the text does not relate to the query, simply state 'Found Nothing'. Ignore outlier "\
              "search results which has nothing to do with the question. Only answer what is asked. The "\
              "answer should be short and concise.\n\nQuery: {question}\nAnswer: "
    
    prompt += f"Query: {question}\nAnswer:"
    answer = generate_text(prompt)
    return answer

# Function to handle user inputs, process the PDF, and generate an answer
def question_answer(url, file, question, api_key):
    openai.api_key = api_key

    if url.strip() == '' and file == None:
        return '[ERROR]: Both URL and PDF is empty. Provide at least one.'
    
    if url.strip() != '' and file != None:
        return '[ERROR]: Both URL and PDF is provided. Please provide only one (either URL or PDF).'

    if url.strip() != '':
        glob_url = url
        download_pdf(glob_url, 'corpus.pdf')
        load_recommender('corpus.pdf')

    else:
        old_file_name = file.name
        file_name = file.name
        file_name = file_name[:-12] + file_name[-4:]
        os.rename(old_file_name, file_name)
        load_recommender(file_name)

    if question.strip() == '':
        return '[ERROR]: Question field is empty'

    return generate_answer(question)

title = 'PDF_GPT'
description = "Based on Pritish's BookGPT, PDF_GPT allows users to input PDFs and ask questions about their contents. This app uses GPT-3 to generate answers based on the PDF's information. References and page numbers are added for improved credibility."

with gr.Blocks() as demo:

    gr.Markdown(f'<center><h1>{title}</h1></center>')
    gr.Markdown(description)
    gr.Markdown("To use, enter OpenAI API Key ")

    with gr.Row():

        with gr.Group():
            url = gr.Textbox(label='URL')
            gr.Markdown("<center><h6>or<h6></center>")
            file = gr.File(label='PDF', file_types=['.pdf'])
            question = gr.Textbox(label='Question')
            api_key = gr.Textbox(label = 'OpenAI API Key', type = 'password')
            btn = gr.Button(value='Submit')
            btn.style(full_width=True)

        with gr.Group():
            answer = gr.Textbox(label='answer')

        btn.click(question_answer, inputs=[url, file, question, api_key], outputs=[answer])

demo.launch()
