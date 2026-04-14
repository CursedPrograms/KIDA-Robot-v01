# How to Test Model Performance on a Hailo Device

This guide explains how to measure and analyze the performance of a model on your Hailo device. We describe two approaches:

1. **Raw Device Benchmarking using `hailortcli`**  
   - Measures the **maximum inference throughput** of the Hailo device by running the model’s `.hef` file directly.
   - Does **not** include host-based pre- or post-processing.
   - Provides the **raw hardware FPS**.

2. **Application-Level Benchmarking using PySDK**  
   - Uses a PySDK benchmarking script (`pysdkProfile.py`) for profiling the inference pipeline in PySDK.

---

## **1. Using `hailortcli` for Raw Performance Benchmarking**

The `hailortcli` tool can be used to check the raw maximum performance of your Hailo device on a specific model.

Run the following command in your terminal:

```bash
hailortcli run <MODEL_NAME>.hef
```

For example, if you want to test a face detection model:

```bash
hailortcli run yolov8n_relu6_face.hef
```

### **Locating the `.hef` Model File**

If you have run AI Hub models locally via PySDK, they are cached locally. You can search for a specific model file (e.g., for `"yolov8n_relu6_face"`) in the DeGirum cache directory using:

```bash
find ~/.local/share/DeGirum/ -name "*yolov8n_relu6_face*.hef"
```

This command helps you confirm the model file location before running the benchmark.

---

## **2. Using PySDK Benchmarking Script**

For a performance measurement through PySDK, the benchmark script (`pysdkProfile.py`) is used. Find it adjacent to this guide in the repository.


### **How to Run the PySDK Benchmark Script**

From the root directory of your repository, run:

```bash
python pysdkProfile.py
```

The script will output the observed FPS, giving you a performance number that you can expect to achieve using PySDK.

---

## **3. Performance Analysis Tips**

- **Raw vs. Application-Level Performance:**  
  - The `hailortcli` benchmark reflects the **maximum raw throughput** of the Hailo device.
  - However, as with any AI accelerator, the real-world performance of the application depends on the **host-side processing** speed as well.
- **Understanding Limitations:**  
  Keep in mind that host-side processing (such as image resizing, overlay rendering, server communication, and post-processing) on the host CPU will reduce the effective FPS compared to the raw hardware capability.

---

## **4. Note on inference servers**

- Both the Hailo-provided multi-process service and the DeGirum AIServer can be used for running multiple models across processes.
- However, this comes with a performance overhead which can affect the overall throughput on weaker systems (e.g. Raspberry Pi).
- For best performance, consider running models **in the same process** (multi-threading is OK) and turn OFF `hailort.service` if it's not needed.

---

## **5. Debugging Performance Bottlenecks**

Even if your Hailo device shows high raw throughput, the actual application-level FPS may be lower due to host-side constraints. Use the following steps to diagnose and potentially remedy these issues:

### **5.1 Check CPU Utilization**

- **Monitor CPU Usage:**  
  Use tools like `htop`, `top` to see if the CPU is running near 100%. High CPU usage during inference might indicate that heavy pre- or post-processing tasks are overloading the host, limiting overall performance.
  
### **5.2 Verify Input Framerate Constraints**

- **Fixed Input Framerate:**  
  If your pipeline sources data from a camera (for example, a 30FPS camera), the input framerate might be the limiting factor (e.g. the pipeline will run at 30FPS maximum).
  - **Note:** Even if the Hailo device can process more frames per second, such pipelines will only handle as many frames as are provided by the camera.

### **5.3 Test the Impact of Hailo Service**

- **Disable the Hailo Multi-Process Service:**  
  On some systems—especially lower-powered ones like the Raspberry Pi—the `hailort.service` can add significant overhead. To see if it’s affecting performance, stop the service and re-run your PySDK application.
  
  ```bash
  sudo systemctl stop hailort.service
  ```

  Note that this will only allow one process to use the device at a time if using `@local`. **You can still have multi-process capabilities by using an AIServer for inference instead of the multi process service! See https://docs.degirum.com/pysdk/user-guide-pysdk/setting-up-an-ai-server**

  ---

### **6. Need Help?**

Feel free to reach out to our community if you have any further questions or need additional assistance! [DeGirum Community](https://community.degirum.com)