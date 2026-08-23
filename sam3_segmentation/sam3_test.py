import torch
from PIL import Image
from sam3.model_builder import build_sam3_image_model
from sam3.model.sam3_image_processor import Sam3Processor

model = build_sam3_image_model()
processor = Sam3Processor(model)

# your actual frame on the ElementsSE drive
image_path = "/media/its/ElementsSE/carla_capture/scenario_1/clear_day/rgb/000087.png"
image = Image.open(image_path).convert("RGB")

inference_state = processor.set_image(image)
output = processor.set_text_prompt(state=inference_state, prompt="pedestrian")

masks, boxes, scores = output["masks"], output["boxes"], output["scores"]
print("found", len(scores), "instances")
