import streamlit as st

st.set_page_config(page_title="Bill2Health", page_icon="🧾")

st.title("Bill2Health")
st.write("Upload a medical bill for analysis")

uploaded_file = st.file_uploader("Choose a medical bill (PDF)", type=["pdf"])

if uploaded_file is not None:
    st.success(f"Uploaded: {uploaded_file.name}")
