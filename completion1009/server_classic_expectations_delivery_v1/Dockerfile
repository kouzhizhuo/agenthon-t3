FROM ghcr.io/kouzhizhuo/agenthon-t3-classic@sha256:c1b3c9f2aec8d5a761b4814cfddf7b79b76eb6afd09ca6bd4558661e2ce046ba AS construction
USER 0
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev && rm -rf /var/lib/apt/lists/*
COPY completion1009 /opt/classic-native-kernels-v1/completion1009
COPY harness/construction.py /opt/t3-classic-structural-v2/construction.py
RUN python -B /opt/t3-classic-structural-v2/construction.py
FROM ghcr.io/kouzhizhuo/agenthon-t3-classic@sha256:c1b3c9f2aec8d5a761b4814cfddf7b79b76eb6afd09ca6bd4558661e2ce046ba AS delivery
USER 0
COPY --from=construction /opt/classic-native-kernels-v1/completion1009/candidates/classic_build_expectations_v1 /opt/classic-native-kernels-v1/completion1009/candidates/classic_build_expectations_v1
COPY --from=construction /opt/classic-native-kernels-v1/structural-v2-construction /opt/classic-native-kernels-v1/structural-v2-construction
COPY completion1009/candidates/lean_production_native_projection_v1 /opt/classic-native-kernels-v1/completion1009/candidates/lean_production_native_projection_v1
COPY harness /opt/t3-classic-structural-v2
COPY harness/delivery_entry.py /opt/classic-native-kernels-v1/delivery_entry.py
COPY harness/LICENSE-SUBMISSION /licenses/LICENSE-SUBMISSION
RUN find /opt/t3-classic-structural-v2 -type d -exec chmod 755 {} + && find /opt/t3-classic-structural-v2 -type f -exec chmod 644 {} + && find /opt/classic-native-kernels-v1/completion1009/candidates/classic_build_expectations_v1 /opt/classic-native-kernels-v1/completion1009/candidates/lean_production_native_projection_v1 -type d -exec chmod 755 {} + && find /opt/classic-native-kernels-v1/completion1009/candidates/classic_build_expectations_v1 /opt/classic-native-kernels-v1/completion1009/candidates/lean_production_native_projection_v1 -type f -exec chmod 644 {} + && chmod 644 /opt/classic-native-kernels-v1/delivery_entry.py /licenses/LICENSE-SUBMISSION
LABEL qfbench2.interface_version="2.0" org.opencontainers.image.licenses="BSD-3-Clause" qfbench2.license="BSD-3-Clause"
ENV OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 PYTHONHASHSEED=0 PYTHONDONTWRITEBYTECODE=1
USER 65534:65534
WORKDIR /output
ENTRYPOINT ["/usr/local/bin/python","-B","/opt/classic-native-kernels-v1/delivery_entry.py"]
CMD []
