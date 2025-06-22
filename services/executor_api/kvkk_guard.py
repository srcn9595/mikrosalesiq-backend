import os
import re
from transformers import AutoTokenizer, AutoModelForTokenClassification, pipeline

NER_MODEL_ID = os.getenv("NER_MODEL", "savasy/bert-base-turkish-ner-cased")
LOCAL_ONLY = os.getenv("HF_LOCAL_ONLY", "false").lower() == "true"

tokenizer = AutoTokenizer.from_pretrained(NER_MODEL_ID, local_files_only=LOCAL_ONLY)
model = AutoModelForTokenClassification.from_pretrained(NER_MODEL_ID, local_files_only=LOCAL_ONLY)
ner_pipeline = pipeline("ner", model=model, tokenizer=tokenizer, aggregation_strategy="simple")

SENSITIVE_ENTITIES = {"PER", "ORG", "LOC"}

def clean_word(word: str) -> str:
    return re.sub(r"[^\wğüşöçıİĞÜŞÖÇ]", "", word)

def mask_word(word: str) -> str:
    word = word.strip()
    if len(word) <= 2:
        return "*" * len(word)
    elif len(word) <= 4:
        return word[0] + "*" * (len(word) - 1)
    else:
        return word[0] + "*" * (len(word) - 2) + word[-1]


def mask_email_word(email: str) -> str:
    try:
        local, domain = email.split("@", 1)
        if len(local) <= 1:
            masked_local = "*"
        elif len(local) == 2:
            masked_local = local[0] + "*"
        else:
            masked_local = local[0] + "*" * (len(local) - 2) + local[-1]
        return f"{masked_local}@{domain.lower()}"  # domain olduğu gibi korunuyor
    except Exception:
        return "****@****"

def mask_address_details(text: str) -> str:
    # Daha fazla adres bileşeni eklendi
    return re.sub(r'\b(?:Mahalle|Mah\.?|Sokak|Sk\.?|Cadde|Cd\.?|Blok|No|Daire|Apartman)[^\n]{0,20}\b',
                  lambda m: m.group(0).split()[0] + " ***", text, flags=re.IGNORECASE)

def mask_iban(text: str) -> str:
    return re.sub(r'\bTR\d{2}(?:[ ]?\d{4}){5}(?:[ ]?\d{0,2})?\b',
                  lambda m: "TR************" + m.group()[-4:], text, flags=re.IGNORECASE)

def mask_credit_card(text: str) -> str:
    return re.sub(r'\b(?:\d[ -]?){13,19}\d\b',
                  lambda m: "*" * len(re.sub(r"[ -]", "", m.group())), text)

def mask_tc_identity(text: str) -> str:
    return re.sub(r'\b\d{11}\b', "***********", text)

def mask_emails(text: str) -> str:
    return re.sub(r'\b[a-zA-Z0-9_.+-]+@[\w-]+\.[\w.-]+\b',
                  lambda m: mask_email_word(m.group()), text)

def mask_sensitive_info(text: str) -> str:
    try:
        entities = ner_pipeline(text)
        entities = sorted(entities, key=lambda e: -e["start"])
        for ent in entities:
            if ent["entity_group"] in SENSITIVE_ENTITIES:
                original = text[ent["start"]:ent["end"]]
                cleaned = clean_word(original)
                if not cleaned:
                    continue
                masked = mask_word(cleaned)
                text = text[:ent["start"]] + masked + text[ent["end"]:]
    except Exception:
        pass  # NER hatası varsa regex'lerle devam et

    text = mask_iban(text)
    text = mask_credit_card(text)
    text = mask_tc_identity(text)
    text = mask_emails(text)
    text = mask_address_details(text)

    return text
