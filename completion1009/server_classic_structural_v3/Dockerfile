FROM ghcr.io/kouzhizhuo/agenthon-t3-classic@sha256:c1b3c9f2aec8d5a761b4814cfddf7b79b76eb6afd09ca6bd4558661e2ce046ba AS construction
USER 0
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev && rm -rf /var/lib/apt/lists/*
COPY completion1009 /opt/classic-native-kernels-v1/completion1009
COPY harness/construction.py /opt/t3-classic-structural-v2/construction.py
RUN python -B /opt/t3-classic-structural-v2/construction.py
FROM ghcr.io/kouzhizhuo/agenthon-t3-classic@sha256:c1b3c9f2aec8d5a761b4814cfddf7b79b76eb6afd09ca6bd4558661e2ce046ba AS screen
USER 0
COPY --from=construction /opt/classic-native-kernels-v1/completion1009/candidates/classic_build_expectations_v1 /opt/classic-native-kernels-v1/completion1009/candidates/classic_build_expectations_v1
COPY --from=construction /opt/classic-native-kernels-v1/completion1009/candidates/classic_price_index_v3 /opt/classic-native-kernels-v1/completion1009/candidates/classic_price_index_v3
COPY --from=construction /opt/classic-native-kernels-v1/structural-v2-construction /opt/classic-native-kernels-v1/structural-v2-construction
COPY completion1009/candidates/lean_production_native_projection_v1 /opt/classic-native-kernels-v1/completion1009/candidates/lean_production_native_projection_v1
COPY harness /opt/t3-classic-structural-v2
RUN find /opt/t3-classic-structural-v2 -type d -exec chmod 755 {} + && find /opt/t3-classic-structural-v2 -type f -exec chmod 644 {} + && find /opt/classic-native-kernels-v1/completion1009/candidates/classic_build_expectations_v1 /opt/classic-native-kernels-v1/completion1009/candidates/classic_price_index_v3 /opt/classic-native-kernels-v1/completion1009/candidates/lean_production_native_projection_v1 -type d -exec chmod 755 {} + && find /opt/classic-native-kernels-v1/completion1009/candidates/classic_build_expectations_v1 /opt/classic-native-kernels-v1/completion1009/candidates/classic_price_index_v3 /opt/classic-native-kernels-v1/completion1009/candidates/lean_production_native_projection_v1 -type f -exec chmod 644 {} +
USER 65534:65534
WORKDIR /output
ENTRYPOINT ["/usr/local/bin/python","-B","/opt/t3-classic-structural-v2/production_entry.py"]
CMD []
