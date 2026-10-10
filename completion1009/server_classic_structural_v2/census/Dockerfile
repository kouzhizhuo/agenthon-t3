FROM ghcr.io/kouzhizhuo/agenthon-t3-classic@sha256:c1b3c9f2aec8d5a761b4814cfddf7b79b76eb6afd09ca6bd4558661e2ce046ba
USER 0
COPY entry.py /opt/t3-structural-census-v1/entry.py
RUN chmod 755 /opt/t3-structural-census-v1 && chmod 644 /opt/t3-structural-census-v1/entry.py
USER 65534:65534
WORKDIR /output
ENTRYPOINT ["/usr/local/bin/python","-B","/opt/t3-structural-census-v1/entry.py"]
CMD []
