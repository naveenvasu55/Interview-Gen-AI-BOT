import streamlit as st
st.title("This is a title text")
st.title('_This_ is :blue[a title] :speech_balloon:')
st.title('$E = mc^2$')
st.header('This is a header')
st.subheader('This is a subheader')

# Streamlit offers 3 text methods - st.text , st.markdown , st.write

st.text("This is a plain text with no formatting")
st.markdown("# This is a header\n **This is a bold text** \n - This is a list item")
st.write('This is a plain text using st.write')
data = {"Name" : "Alice", "Age" : 30, "Ocupation": "Engineer"}
st.write(data)



# Streamlit offers 3 Chat elements  - st.chat_input , st.chat_message , st.write_stream
with st.chat_message("AI") :
    st.write("Hello there!")

prompt = st.chat_input("Type your message", max_chars = 500)
if prompt :
    st.write(f"User message : {prompt}")
