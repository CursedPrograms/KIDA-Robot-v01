import numpy as np
import os
from hailo_platform import (HEF, VDevice, HailoSchedulingAlgorithm, FormatType)
from transformers import AutoTokenizer
from queue import Queue, Empty
from threading import Thread
from common.postprocessing import apply_repetition_penalty

# All decoder assets live here — not relative to __file__
RESOURCES_DIR = "/home/kida-01/Desktop/Kida-Robot/resources"


class HailoWhisperPipeline:

    def __init__(self, encoder_model_path=None, decoder_model_path=None,
                 variant="tiny", host="arm64", multi_process_service=False):

        if encoder_model_path is None:
            encoder_model_path = os.path.join(
                RESOURCES_DIR, "hefs/h8l/base/base-whisper-encoder-5s_h8l.hef"
            )
        if decoder_model_path is None:
            decoder_model_path = os.path.join(
                RESOURCES_DIR, "hefs/h8l/base/base-whisper-decoder-fixed-sequence-matmul-split_h8l.hef"
            )

        self.encoder_model_path = encoder_model_path
        self.decoder_model_path = decoder_model_path
        self.timeout_ms = 100000000
        self.variant = variant
        self.decoding_sequence_length = 32 if self.variant == "tiny" else 24
        self.host = host
        self.multi_process_service = multi_process_service

        self.token_embedding_weight = self._load_token_embedding_weight()
        self.onnx_add_input = self._load_onnx_add_input()
        self.constant_output_0 = np.array([1])
        self._load_tokenizer()

        self.data_queue = Queue()
        self.results_queue = Queue()
        self.running = True
        self.thread = Thread(target=self._inference_loop)
        self.thread.start()

    def _load_token_embedding_weight(self):
        file_path = os.path.join(
            RESOURCES_DIR,
            f"decoder_assets/{self.variant}/decoder_tokenization/token_embedding_weight_{self.variant}.npy"
        )
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"[ERROR] Missing token embedding: {file_path}")
        return np.load(file_path)

    def _load_onnx_add_input(self):
        file_path = os.path.join(
            RESOURCES_DIR,
            f"decoder_assets/{self.variant}/decoder_tokenization/onnx_add_input_{self.variant}.npy"
        )
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"[ERROR] Missing ONNX add input: {file_path}")
        return np.load(file_path)

    def _load_tokenizer(self):
        self.tokenizer = AutoTokenizer.from_pretrained(f"openai/whisper-{self.variant}")

    def _tokenization(self, decoder_input_ids):
        gather_output  = self.token_embedding_weight[decoder_input_ids]
        add_output     = gather_output + self.onnx_add_input
        unsqueeze_output = np.expand_dims(add_output, axis=int(self.constant_output_0[0]))
        transpose_output = np.transpose(unsqueeze_output, (0, 2, 1, 3))
        return transpose_output

    def _inference_loop(self):
        params = VDevice.create_params()
        params.scheduling_algorithm = HailoSchedulingAlgorithm.ROUND_ROBIN

        if self.multi_process_service:
            params.multi_process_service = True
            params.group_id = "SHARED"

        decoder_hef        = HEF(self.decoder_model_path)
        sorted_output_names = decoder_hef.get_sorted_output_names()
        decoder_model_name  = decoder_hef.get_network_group_names()[0]

        with VDevice(params) as vdevice:
            encoder_infer_model = vdevice.create_infer_model(self.encoder_model_path)
            decoder_infer_model = vdevice.create_infer_model(self.decoder_model_path)
            encoder_infer_model.input().set_format_type(FormatType.FLOAT32)
            encoder_infer_model.output().set_format_type(FormatType.FLOAT32)
            decoder_infer_model.input(f"{decoder_model_name}/input_layer1").set_format_type(FormatType.FLOAT32)
            decoder_infer_model.input(f"{decoder_model_name}/input_layer2").set_format_type(FormatType.FLOAT32)

            for output_name in sorted_output_names:
                decoder_infer_model.output(output_name).set_format_type(FormatType.FLOAT32)

            with encoder_infer_model.configure() as enc_model:
                with decoder_infer_model.configure() as dec_model:
                    enc_bindings = enc_model.create_bindings()
                    dec_bindings = dec_model.create_bindings()

                    while self.running:
                        try:
                            input_mel = self.data_queue.get(timeout=1)
                            input_mel = np.ascontiguousarray(input_mel)

                            enc_bindings.input().set_buffer(input_mel)
                            buffer = np.zeros(encoder_infer_model.output().shape).astype(np.float32)
                            enc_bindings.output().set_buffer(buffer)
                            enc_model.run([enc_bindings], self.timeout_ms)
                            encoded_features = enc_bindings.output().get_buffer()

                            start_token_id    = [50258]
                            decoder_input_ids = np.array([[start_token_id[0]]], dtype=np.int64)
                            decoder_input_ids = np.concatenate(
                                [decoder_input_ids,
                                 np.zeros((1, self.decoding_sequence_length - 1), dtype=np.int64)],
                                axis=1
                            )

                            generated_tokens = []
                            for i in range(self.decoding_sequence_length - 1):
                                tokenized_ids = self._tokenization(decoder_input_ids)

                                dec_bindings.input(f"{decoder_model_name}/input_layer1").set_buffer(encoded_features)
                                dec_bindings.input(f"{decoder_model_name}/input_layer2").set_buffer(tokenized_ids)

                                buffers = [
                                    np.zeros(decoder_infer_model.output(name).shape).astype(np.float32)
                                    for name in sorted_output_names
                                ]
                                for name, buf in zip(sorted_output_names, buffers):
                                    dec_bindings.output(name).set_buffer(buf)

                                dec_model.run([dec_bindings], self.timeout_ms)

                                decoder_outputs = np.concatenate(
                                    [dec_bindings.output(name).get_buffer() for name in sorted_output_names],
                                    axis=2
                                )

                                logits     = apply_repetition_penalty(
                                    decoder_outputs[:, i], generated_tokens, penalty=1.5
                                )
                                next_token = np.argmax(logits)
                                generated_tokens.append(next_token)
                                decoder_input_ids[0][i + 1] = np.array([[next_token]], dtype=np.int64)

                                if next_token == self.tokenizer.eos_token_id:
                                    break

                            transcription = self.tokenizer.decode(
                                generated_tokens, skip_special_tokens=True
                            )
                            self.results_queue.put(transcription)

                        except Empty:
                            pass

    def send_data(self, data):
        self.data_queue.put(data)

    def get_transcription(self):
        return self.results_queue.get()

    def stop(self):
        self.running = False
        self.thread.join()