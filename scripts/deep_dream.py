import sys
from types import ModuleType

# --- STEP 1: FIX FOR PYTHON 3.12 ---
pkg_mock = ModuleType("pkg_resources")
try:
    from packaging.version import parse as parse_version
    pkg_mock.parse_version = parse_version
except ImportError:
    pkg_mock.parse_version = lambda v: [int(x) for x in v.split('.') if x.isdigit()]
sys.modules["pkg_resources"] = pkg_mock

# --- STEP 2: IMPORTS ---
import os
import numpy as np
import tensorflow as tf
from PIL import Image

# --- STEP 3: PREPARE MODEL ---
# Using InceptionV3 - the classic "Dream" model
base_model = tf.keras.applications.InceptionV3(include_top=False, weights='imagenet')

# Maximize the activations of these specific layers
# Mixed3/4/5 are the "trippy" layers with eyes and patterns
names = ['mixed3', 'mixed5']
layers = [base_model.get_layer(name).output for name in names]
dream_model = tf.keras.Model(inputs=base_model.input, outputs=layers)

def deprocess(img):
    img = 255 * (img + 1.0) / 2.0
    return tf.cast(img, tf.uint8)

def calc_loss(img, model):
    img_batch = tf.expand_dims(img, axis=0)
    layer_activations = model(img_batch)
    if len(layer_activations) == 1:
        layer_activations = [layer_activations]

    losses = []
    for act in layer_activations:
        loss = tf.math.reduce_mean(act)
        losses.append(loss)
    return tf.reduce_sum(losses)

@tf.function
def deepdream_step(img, model, step_size):
    with tf.GradientTape() as tape:
        tape.watch(img)
        loss = calc_loss(img, model)
    gradients = tape.gradient(loss, img)
    gradients /= tf.math.reduce_std(gradients) + 1e-8
    img = img + gradients * step_size
    img = tf.clip_by_value(img, -1, 1)
    return loss, img

# --- STEP 4: MAIN PROCESS ---
def run_dream(input_path, output_path, steps=100, step_size=0.01):
    # Load Image
    if not os.path.exists(input_path):
        print(f"Error: {input_path} not found!")
        return

    img = Image.open(input_path).convert('RGB')
    img = img.resize((500, 500)) # Resizing to save your RAM
    img = np.array(img)
    img = tf.keras.applications.inception_v3.preprocess_input(img)
    img = tf.convert_to_tensor(img)

    print(f"Dreaming on {input_path}...")
    for step in range(steps):
        loss, img = deepdream_step(img, dream_model, step_size)
        if step % 20 == 0:
            print(f"Step {step}, Loss {loss.numpy()}")

    # Save Output
    result = deprocess(img)
    final_img = Image.fromarray(result.numpy())

    # Ensure output dir exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    final_img.save(output_path)
    print(f"Success! Dream saved to {output_path}")

if __name__ == "__main__":
    run_dream('input/input.jpg', 'output/output.jpg')
