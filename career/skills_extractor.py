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
        
    # Massive predefined dictionary of valid tech skills to catch regardless of case
    tech_keywords = {
        'golang', 'python', 'java', 'javascript', 'typescript', 'react', 'vue', 'angular',
        'docker', 'kubernetes', 'aws', 'gcp', 'azure', 'sql', 'mysql', 'postgresql', 'mongodb',
        'redis', 'kafka', 'rabbitmq', 'graphql', 'rest', 'linux', 'unix', 'django', 'flask',
        'fastapi', 'spring', 'node.js', 'nodejs', 'express', 'html', 'css', 'sass', 'less',
        'tailwind', 'git', 'github', 'gitlab', 'bitbucket', 'jira', 'confluence', 'agile',
        'scrum', 'kanban', 'machine learning', 'deep learning', 'nlp', 'computer vision',
        'data science', 'pandas', 'numpy', 'scipy', 'scikit-learn', 'tensorflow', 'pytorch',
        'c++', 'c#', 'php', 'ruby', 'swift', 'kotlin', 'dart', 'flutter', 'react native',
        'prompt', 'llm', 'llms', 'openai', 'claude', 'ci/cd', 'tcp/ip', 'pl/sql', 'ux/ui',
        'bash', 'shell', 'graphql', 'grpc', 'terraform', 'ansible', 'jenkins'
    }
    
    # Generic corporate/tech words to aggressively ignore if picked up by NER
    generic_job_words = {
        'software', 'engineer', 'developer', 'manager', 'bachelor', 'master', 'degree',
        'experience', 'years', 'team', 'project', 'system', 'application', 'business', 
        'product', 'development', 'management', 'data', 'design', 'testing', 'support', 
        'working', 'knowledge', 'understanding', 'using', 'strong', 'ability', 'skills',
        'required', 'preferred', 'plus', 'including', 'related', 'field', 'science',
        'computer', 'engineering', 'role', 'responsibilities', 'requirements', 'environment'
    }
    
    # Standard English stopwords (the, and, of, is, etc.)
    stop_words = set(stopwords.words('english'))
    
    candidates = []
    
    # 1. Catch all pre-defined tech keywords regardless of text capitalization
    words = word_tokenize(text)
    for w in words:
        clean_w = w.lower().strip(',.()!?:;')
        if clean_w in tech_keywords:
            candidates.append(clean_w)
            
    # 2. Extract strictly uppercase Acronyms (e.g. API, AWS, iOS - handle special camelCase)
    # This regex looks for 2+ uppercase letters optionally ending in 's' (APIs), or specific tech patterns like iOS, macOS
    strict_acronyms = re.findall(r'\b[A-Z]{2,5}s?\b', text)
    strict_acronyms += re.findall(r'\b(?:iOS|macOS|tvOS)\b', text)
    for ac in strict_acronyms:
        candidates.append(ac)
        
    # 3. Spacy Semantic Entities - Only keep highly specific tech entities if they aren't generic
    doc = nlp(text)
    for ent in doc.ents:
        if ent.label_ in ('PRODUCT', 'ORG'):
            for token in ent.text.split():
                clean_token = token.strip(',.()!?:;')
                if len(clean_token) > 2:
                    candidates.append(clean_token)
                    
    # 4. Processing and Filtering
    unique_skills = []
    seen = set()
    
    # Dynamic context from user args
    if company:
        seen.update(company.lower().split())
    if title:
        seen.update(title.lower().split())
        
    hardcoded_rejects = {
        'dm', 'us', 'usa', 'uk', 'hq', 'vp', 'ceo', 'cfo', 'cto', 'roi', 'kpi', 'okr', 'llc', 'inc', 'ltd',
        'opt', 'cpt', 'h1b', 'ead', 'pto', 'al', 'ak', 'az', 'ar', 'ca', 'co', 'ct', 'de', 'fl', 'ga', 'hi', 
        'id', 'il', 'in', 'ia', 'ks', 'ky', 'la', 'me', 'md', 'ma', 'mi', 'mn', 'ms', 'mo', 'mt', 'ne', 'nv', 
        'nh', 'nj', 'nm', 'ny', 'nc', 'nd', 'oh', 'ok', 'or', 'pa', 'ri', 'sc', 'sd', 'tn', 'tx', 'ut', 'vt', 
        'va', 'wa', 'wv', 'wi', 'wy', 'dc'
    }
    seen.update(hardcoded_rejects)
    seen.update(generic_job_words)
    seen.update(stop_words)
    
    for c in candidates:
        clean_c = c.strip(' -,.*&^%$#@!()[]{}|<>/?`~')
        if clean_c.endswith('.') and not clean_c.lower().endswith('.js') and not clean_c.lower().endswith('.net'):
            clean_c = clean_c[:-1]
            
        # Capitalize specifically if it's an acronym or matched keyword
        display_c = clean_c
        if clean_c.lower() in tech_keywords:
            if clean_c.lower() in ['c++', 'c#', 'ci/cd', 'tcp/ip', 'ux/ui']:
                display_c = clean_c.upper()
            elif clean_c.lower() == 'ios':
                display_c = 'iOS'
            elif len(clean_c) <= 3 and clean_c.lower() not in ['git', 'vue', 'css']:
                display_c = clean_c.upper() # e.g. SQL -> SQL
            else:
                display_c = clean_c.capitalize()
        elif re.match(r'^[A-Z]{2,5}s?$', clean_c):
            display_c = clean_c # Keep strict acronym casing
            
        lower_c = display_c.lower()
        
        # Validation checks
        if len(lower_c) < 2 and lower_c not in ('c', 'r'):
            continue
        if lower_c in seen:
            continue
        if re.match(r'^[\+\-\$\€\£]?\d+(?:[.,]\d+)?(?:[KkMmBb]|\%)?$', lower_c):
            continue # Reject numbers/percentages
            
        seen.add(lower_c)
        unique_skills.append(display_c)
            
    return unique_skills[:20]
