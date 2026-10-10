ARG SCREEN_IMAGE
FROM ${SCREEN_IMAGE}
USER 0
COPY entry.py phase_entry.py /opt/t3-phase/
RUN chmod 755 /opt/t3-phase && chmod 644 /opt/t3-phase/*.py
USER 65534:65534
ENTRYPOINT ["/usr/local/bin/python","-B","/opt/t3-phase/entry.py"]
CMD []
