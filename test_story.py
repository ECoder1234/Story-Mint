import json, os, requests, time

url = 'http://localhost:11434/api/generate'
prompt = 'Write a simple 5-page children story about a boy named Pip. Return ONLY a JSON array. Each element has "page" (number) and "text" (2 sentences). Example: [{"page":1,"text":"Pip woke up. He was happy."}]. Return 5 pages.'

payload = {
    'model': 'mistral',
    'prompt': prompt,
    'stream': False,
    'options': {'temperature': 0.8, 'num_predict': 1024}
}
print('Requesting story from Ollama...')
start = time.time()
r = requests.post(url, json=payload, timeout=600)
elapsed = time.time() - start
data = r.json()
raw = data.get('response', '')
print(f'Response received in {elapsed:.0f}s, {len(raw)} chars')
print('Raw response:')
print(raw[:1000])

# Try to parse
try:
    import re
    json_match = re.search(r'\[.*\]', raw, re.DOTALL)
    if json_match:
        story = json.loads(json_match.group())
        print(f'\nParsed {len(story)} pages successfully!')
        for p in story[:3]:
            print(f'  Page {p.get("page")}: {p.get("text")[:80]}...')
    else:
        print('\nNo JSON array found in response')
except Exception as e:
    print(f'\nParse error: {e}')
