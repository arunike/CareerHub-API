import nltk
from nltk.corpus import stopwords
from nltk.tokenize import word_tokenize
import re

try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt', quiet=True)
    
try:
    nltk.data.find('corpora/stopwords')
except LookupError:
    nltk.download('stopwords', quiet=True)
    
try:
    nltk.data.find('taggers/averaged_perceptron_tagger')
except LookupError:
    nltk.download('averaged_perceptron_tagger', quiet=True)

import spacy

# Load Spacy Model Once
nlp = spacy.load("en_core_web_sm")

def extract_skills_from_text(text: str, company: str = "", title: str = "") -> list[str]:
    if not text:
        return []
        
    doc = nlp(text)
    
    candidates = []
    
    # 0. Pre-defined Explicit Tech Skills to always catch
    tech_keywords = {
        'golang', 'python', 'java', 'javascript', 'typescript', 'react', 'vue', 'angular',
        'docker', 'kubernetes', 'aws', 'gcp', 'azure', 'sql', 'mysql', 'postgresql', 'mongodb',
        'redis', 'kafka', 'rabbitmq', 'graphql', 'rest', 'linux', 'unix', 'django', 'flask',
        'fastapi', 'spring', 'node.js', 'nodejs', 'express', 'html', 'css', 'sass', 'less',
        'tailwind', 'git', 'github', 'gitlab', 'bitbucket', 'jira', 'confluence', 'agile',
        'scrum', 'kanban', 'machine learning', 'deep learning', 'nlp', 'computer vision',
        'data science', 'pandas', 'numpy', 'scipy', 'scikit-learn', 'tensorflow', 'pytorch',
        'c++', 'c#', 'php', 'ruby', 'swift', 'kotlin', 'dart', 'flutter', 'react native',
        'prompt', 'llm', 'llms', 'openai', 'claude'
    }
    
    words = text.replace(',', ' ').replace('.', ' ').split()
    for w in words:
        if w.lower() in tech_keywords:
            candidates.append(w)
    
    # 1. Spacy Semantic Entities (Bypasses regular English nouns like Promote, Campaign, Ads without ANY skip lists!)
    for ent in doc.ents:
        if ent.label_ in ('ORG', 'PRODUCT'):
            # Split multi-word entities (e.g. TikTok DM -> TikTok, DM)
            for token in ent.text.split():
                candidates.append(token)
                
    # 2. Structural Technology Acronym Rules (e.g. API, APIs, iOS, HTML5, CI/CD)
    acronyms = re.findall(r'\b[A-Z][a-zA-Z0-9]*[A-Z0-9]s?\b', text)
    acronyms += re.findall(r'\b[a-z]*[A-Z][a-zA-Z0-9]*[A-Z0-9]s?\b', text)
    acronyms += re.findall(r'\b(?:CI/CD|TCP/IP|PL/SQL)\b', text, re.IGNORECASE)
    
    for ac in acronyms:
        candidates.append(ac)
        
    # 3. Dynamic Context Exclusion
    context_words = set()
    if company:
        context_words.update(company.lower().split())
    if title:
        context_words.update(title.lower().split())
        
    structural_blocks = {'the', 'and', 'for', 'with', 'inc', 'llc', 'ltd'}
    context_words.update(structural_blocks)
    
    # Reject bad acronyms or acronyms that are too generic
    hardcoded_rejects = {'dm', 'us', 'u.s', 'u.s.', 'usa', 'uk', 'hq', 'vp', 'ceo', 'cfo', 'cto', 'roi', 'kpi', 'okr'}
    
    unique_skills = []
    seen = set(context_words)
    
    for c in candidates:
        if c.lower() in hardcoded_rejects:
            continue
        # Clean punctuation from edges
        c = re.sub(r'^[^a-zA-Z0-9+#.]+|[^a-zA-Z0-9+#.]+$', '', c)
        if c.endswith('.') and not c.lower().endswith('.js') and not c.lower().endswith('.net'):
            c = c[:-1]
            
        if len(c) < 2 and c not in ('C', 'R'):
            continue
            
        # Reject raw math numbers, percentages, salaries, and metrics (298K, 5M, 19%)
        if re.match(r'^[\+\-\$\€\£]?\d+(?:[.,]\d+)?(?:[KkMmBb]|\%)?$', c):
            continue
            
        # Reject slashed rates like K/day
        if '/' in c and c.upper() not in ('CI/CD', 'TCP/IP', 'PL/SQL', 'UX/UI', 'UI/UX'):
            continue
            
        if c.lower() not in seen:
            seen.add(c.lower())
            unique_skills.append(c)
            
    return unique_skills[:15]
