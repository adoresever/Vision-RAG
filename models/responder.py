# models/responder.py

from models.model_loader import load_model
from transformers import GenerationConfig
import google.generativeai as genai
from dotenv import load_dotenv
from logger import get_logger
from openai import OpenAI
from PIL import Image
import torch
import base64
import os
import io


logger = get_logger(__name__)

# Function to encode the image
def encode_image(image_path):
  with open(image_path, "rb") as image_file:
    return base64.b64encode(image_file.read()).decode('utf-8')

def generate_response(images, query, session_id, resized_height=280, resized_width=280, model_choice='qwen'):
    """
    Generates a response using the selected model based on the query and images.
    """
    try:
        logger.info(f"Generating response using model '{model_choice}'.")
        if model_choice == 'qwen':
            from qwen_vl_utils import process_vision_info
            # Load cached model
            model, processor, device = load_model('qwen')
            # Ensure dimensions are multiples of 28
            resized_height = (resized_height // 28) * 28
            resized_width = (resized_width // 28) * 28

            image_contents = []
            for image in images:
                image_contents.append({
                    "type": "image",
                    "image": os.path.join('static', image),
                    "resized_height": resized_height,
                    "resized_width": resized_width
                })
            messages = [
                {
                    "role": "user",
                    "content": image_contents + [{"type": "text", "text": query}],
                }
            ]
            text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            image_inputs, video_inputs = process_vision_info(messages)
            inputs = processor(
                text=[text],
                images=image_inputs,
                videos=video_inputs,
                padding=True,
                return_tensors="pt",
            )
            inputs = inputs.to(device)
            generated_ids = model.generate(**inputs, max_new_tokens=128)
            generated_ids_trimmed = [
                out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
            ]
            output_text = processor.batch_decode(
                generated_ids_trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
            )
            logger.info("Response generated using Qwen model.")
            return output_text[0]
        
        elif model_choice == 'gemini':
            
            model, _ = load_model('gemini')
            
            try:
                content = []
                content.append(query)  # Add the text query first
                
                for img_path in images:
                    full_path = os.path.join('static', img_path)
                    if os.path.exists(full_path):
                        try:
                            img = Image.open(full_path)
                            content.append(img)
                        except Exception as e:
                            logger.error(f"Error opening image {full_path}: {e}")
                    else:
                        logger.warning(f"Image file not found: {full_path}")
                
                if len(content) == 1:  # Only text, no images
                    return "No images could be loaded for analysis."
                
                response = model.generate_content(content)
                
                if response.text:
                    generated_text = response.text
                    logger.info("Response generated using Gemini model.")
                    return generated_text
                else:
                    return "The Gemini model did not generate any text response."
            
            except Exception as e:
                logger.error(f"Error in Gemini processing: {str(e)}", exc_info=True)
                return f"An error occurred while processing the images: {str(e)}"
        
        elif model_choice == 'gpt4':
            api_key = os.getenv("OPENAI_API_KEY")
            client = OpenAI(api_key=api_key)
            
            try:
                content = [{"type": "text", "text": query}]
                
                for img_path in images:
                    full_path = os.path.join('static', img_path)
                    if os.path.exists(full_path):
                        base64_image = encode_image(full_path)
                        content.append({
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            }
                        })
                    else:
                        logger.warning(f"Image file not found: {full_path}")
                
                if len(content) == 1:  # Only text, no images
                    return "No images could be loaded for analysis."
                
                response = client.chat.completions.create(
                    model="gpt-4o",  # Make sure to use the correct model name
                    messages=[
                        {
                            "role": "user",
                            "content": content
                        }
                    ],
                    max_tokens=1024
                )
                
                generated_text = response.choices[0].message.content
                logger.info("Response generated using GPT-4 model.")
                return generated_text
            
            except Exception as e:
                logger.error(f"Error in GPT-4 processing: {str(e)}", exc_info=True)
                return f"An error occurred while processing the images: {str(e)}"
        
        elif model_choice == 'llama-vision':
            # Load model, processor, and device
            model, processor, device = load_model('llama-vision')

            # Process images
            image_paths = [os.path.join('static', image) for image in images]
            # For simplicity, use the first image
            image_path = image_paths[0]
            image = Image.open(image_path).convert('RGB')

            # Prepare messages
            messages = [
                {"role": "user", "content": [
                    {"type": "image"},
                    {"type": "text", "text": query}
                ]}
            ]
            input_text = processor.apply_chat_template(messages, add_generation_prompt=True)
            inputs = processor(image, input_text, return_tensors="pt").to(device)

            # Generate response
            output = model.generate(**inputs, max_new_tokens=512)
            response = processor.decode(output[0], skip_special_tokens=True)
            return response
        
        elif model_choice == "pixtral":

            model, sampling_params, device = load_model('pixtral')


            def image_to_data_url(image_path):

                image_path = os.path.join('static', image_path) 
                
                with open(image_path, "rb") as image_file:
                    encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
                ext = os.path.splitext(image_path)[1][1:]  # Get the file extension
                return f"data:image/{ext};base64,{encoded_string}"
            
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": query},
                        *[{"type": "image_url", "image_url": {"url": image_to_data_url(img_path)}} for i, img_path in enumerate(images) if i<1]
                    ]
                },
            ]

            outputs = model.chat(messages, sampling_params=sampling_params)
            return outputs[0].outputs[0].text
        
        elif model_choice == "molmo":
            model, processor, device = load_model('molmo')
            model = model.half()  # Convert model to half precision
            pil_images = []
            for img_path in images[:1]:  # Process only the first image for now
                full_path = os.path.join('static', img_path)
                if os.path.exists(full_path):
                    try:
                        img = Image.open(full_path).convert('RGB')
                        pil_images.append(img)
                    except Exception as e:
                        logger.error(f"Error opening image {full_path}: {e}")
                else:
                    logger.warning(f"Image file not found: {full_path}")

            if not pil_images:
                return "No images could be loaded for analysis."

            try:
                # Process the images and text
                inputs = processor.process(
                    images=pil_images,
                    text=query
                )

                # Move inputs to the correct device and make a batch of size 1
                # Convert float tensors to half precision, but keep integer tensors as they are
                inputs = {k: (v.to(device).unsqueeze(0).half() if v.dtype in [torch.float32, torch.float64] else 
                            v.to(device).unsqueeze(0))
                        if isinstance(v, torch.Tensor) else v 
                        for k, v in inputs.items()}

                # Generate output
                with torch.no_grad():  # Disable gradient calculation
                    output = model.generate_from_batch(
                        inputs,
                        GenerationConfig(max_new_tokens=200, stop_strings="<|endoftext|>"),
                        tokenizer=processor.tokenizer
                    )

                # Only get generated tokens; decode them to text
                generated_tokens = output[0, inputs['input_ids'].size(1):]
                generated_text = processor.tokenizer.decode(generated_tokens, skip_special_tokens=True)

                return generated_text

            except Exception as e:
                logger.error(f"Error in Molmo processing: {str(e)}", exc_info=True)
                return f"An error occurred while processing the images: {str(e)}"
            finally:
                # Close the opened images to free up resources
                for img in pil_images:
                    img.close()              
        else:
            logger.error(f"Invalid model choice: {model_choice}")
            return "Invalid model selected."
    except Exception as e:
        logger.error(f"Error generating response: {e}")
        return "An error occurred while generating the response."