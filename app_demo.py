import time
import streamlit as st
from classifier import classify_intent
from rag_chain import generate_reply

st.set_page_config(page_title="Dental CS Agent", layout="wide")
st.title("Dental Customer Service Agent")
st.caption("Paste a client email and click Run to generate a reply draft.")

col1, col2 = st.columns([1, 1])

with col1:
    email_input = st.text_area(
        "Client email",
        height=260,
        placeholder="Paste email text here — any language...",
    )
    run = st.button("Run", type="primary", use_container_width=True)

with col2:
    if run and email_input.strip():
        with st.spinner("Classifying..."):
            classification = classify_intent(email_input)
            time.sleep(15)

        language = classification.get("language", "en")
        intent = classification.get("intent", "OTHER")
        escalate = classification.get("escalate", False)
        reason = classification.get("reason", "")

        st.markdown(f"**Language detected:** `{language}`")
        st.markdown(f"**Intent:** `{intent}`")
        st.markdown(f"**Reason:** {reason}")

        if escalate:
            st.error(
                "Flagged for human review — do not auto-send. "
                "This email requires a human response."
            )
        else:
            with st.spinner("Retrieving from knowledge base..."):
                result = generate_reply(email_input, language)

            st.markdown("**Reply draft:**")
            st.text_area(
                "Draft (copy and review before sending)",
                value=result["reply"],
                height=260,
            )

            with st.expander("Knowledge base sources retrieved"):
                for source in result["sources"]:
                    st.caption(source)

    elif run:
        st.warning("Please paste an email before clicking Run.")
