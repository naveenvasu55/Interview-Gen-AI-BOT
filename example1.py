import streamlit as st
#Session STATE

# Example 1 - Saving state
st.title("Nested Button Example")

if st.button("First Button") :
       st.write("First Button clicked")
       if st.button("Second Button") :
        st.write("Second Button clicked")



# Example 2 - Saving state
st.title("Nested Button Example with state for 1st button")

if 'show_second_button' not in st.session_state:
   st.session_state.show_second_button = False
if st.button("First Button!") :
    st.session_state.show_second_button = True

if st.session_state.show_second_button:
       st.write("First Button clicked")
       if st.button("Second Button!") :
        st.write("Second Button clicked")


# Example 3 - Display the content of only 1 respective button upon clicked
# (eg : If you clicked first button, it shows the content of first button not the second one & viceversa)
st.title("Nested Button Example with state")

if 'show_second_button' not in st.session_state:
   st.session_state.show_second_button = False
if st.button("First Button!!") :
    st.session_state.show_second_button = True
    st.write("First Button clicked")

if st.session_state.show_second_button:
       if st.button("Second Button!!") :
        st.write("Second Button clicked")


# Example 4 - Saving state for 2nd button
st.title("Nested Button Example with state for  2nd button")

if 'show_second_button2' not in st.session_state:
   st.session_state.show_second_button2 = False

if "second_button_clicked" not in st.session_state:
    st.session_state.second_button_clicked = False

if st.button("First Button!!!") :
    st.session_state.show_second_button2 = True

if st.session_state.show_second_button2:
       st.write("First Button clicked")
       if st.button("Second Button!!!") :
          st.session_state.second_button_clicked = True
       if st.session_state.second_button_clicked:
          st.write("Second Button clicked")