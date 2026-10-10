FROM TESTED_SCREEN AS tested_screen
FROM ghcr.io/kouzhizhuo/agenthon-t3@sha256:5a190afe0bdfe7685e64cbf1aec30d39885199c85f688a971b8d4a0ab8d217eb AS delivery
USER 0
RUN python -m pip install --no-cache-dir Cython==3.1.3
COPY --from=tested_screen /opt/classic-native-kernels-v1/completion1009/candidates/classic_native_kernels_v1 /opt/classic-native-kernels-v1/completion1009/candidates/classic_native_kernels_v1
COPY delivery_entry.py /opt/classic-native-kernels-v1/delivery_entry.py
COPY LICENSE-SUBMISSION /licenses/LICENSE-SUBMISSION
RUN find /opt/classic-native-kernels-v1 -type d -exec chmod 755 {} + && find /opt/classic-native-kernels-v1 -type f -exec chmod 644 {} +
LABEL org.opencontainers.image.source="https://github.com/kouzhizhuo/agenthon-t3" qfbench2.interface_version="2.0" org.opencontainers.image.licenses="BSD-3-Clause" org.opencontainers.image.title="T3 exact classic native simulator"
ENV PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 PYTHONHASHSEED=0
USER 65534:65534
WORKDIR /output
ENTRYPOINT ["/usr/local/bin/python","-B","/opt/classic-native-kernels-v1/delivery_entry.py"]
CMD []
