      >>SOURCE FORMAT FREE
*> kida-report.cob — batch summary report over KIDA's run log.
*>
*> COBOL's actual strength is sequential batch record processing, so this
*> is a genuine (if unusual) fit rather than a forced one: read every line
*> of logs/kida_run.log once, tally known ASCII markers, print a summary.
*>
*> Takes one argument: the path to a *pre-cleaned* copy of the log (see
*> run_report.sh). The real kida_run.log occasionally contains raw binary
*> — leftover NUL bytes from mid-session serial-port debugging — which can
*> produce a single pathological "line" of megabytes with no newline in
*> it. run_report.sh strips that with `grep -a .` before handing this
*> program a normal text file; this program still caps each line read at
*> 2000 chars (LOG-LINE's size) as a second line of defense, so a marker
*> that happens to fall past that point in one abnormally long line would
*> be undercounted rather than crashing the run — an accepted, disclosed
*> approximation for a summary tool, not a source of truth.
IDENTIFICATION DIVISION.
PROGRAM-ID. KIDA-REPORT.

ENVIRONMENT DIVISION.
INPUT-OUTPUT SECTION.
FILE-CONTROL.
    SELECT LOG-FILE ASSIGN TO WS-INPUT-PATH
        ORGANIZATION IS LINE SEQUENTIAL
        FILE STATUS IS WS-FILE-STATUS.

DATA DIVISION.
FILE SECTION.
FD  LOG-FILE.
01  LOG-LINE                    PIC X(2000).

WORKING-STORAGE SECTION.
01  WS-INPUT-PATH               PIC X(256).
01  WS-FILE-STATUS              PIC XX.
01  WS-EOF                      PIC X VALUE "N".
    88  END-OF-FILE             VALUE "Y".

01  WS-LINE-COUNT               PIC 9(9) VALUE 0.
01  WS-STARTS-COUNT             PIC 9(9) VALUE 0.
01  WS-MODE-COUNT               PIC 9(9) VALUE 0.
01  WS-HAILO-ERR-COUNT          PIC 9(9) VALUE 0.
01  WS-TRACEBACK-COUNT          PIC 9(9) VALUE 0.
01  WS-IO-ERR-COUNT             PIC 9(9) VALUE 0.
01  WS-DISCONNECT-COUNT         PIC 9(9) VALUE 0.
01  WS-TALLY                    PIC 9(9) VALUE 0.

01  WS-DISPLAY-9                PIC ZZZ,ZZZ,ZZ9.

PROCEDURE DIVISION.
MAIN-PARA.
    ACCEPT WS-INPUT-PATH FROM COMMAND-LINE
    IF WS-INPUT-PATH = SPACES
        DISPLAY "Usage: kida-report <cleaned-log-path>"
        STOP RUN
    END-IF

    OPEN INPUT LOG-FILE
    IF WS-FILE-STATUS NOT = "00"
        DISPLAY "Could not open " FUNCTION TRIM(WS-INPUT-PATH)
            " (status " WS-FILE-STATUS ")"
        STOP RUN
    END-IF

    PERFORM UNTIL END-OF-FILE
        READ LOG-FILE
            AT END
                MOVE "Y" TO WS-EOF
            NOT AT END
                PERFORM COUNT-LINE
        END-READ
    END-PERFORM

    CLOSE LOG-FILE
    PERFORM PRINT-REPORT
    STOP RUN.

COUNT-LINE.
    ADD 1 TO WS-LINE-COUNT

    MOVE 0 TO WS-TALLY
    INSPECT LOG-LINE TALLYING WS-TALLY FOR ALL "Starting main.py at"
    ADD WS-TALLY TO WS-STARTS-COUNT

    MOVE 0 TO WS-TALLY
    INSPECT LOG-LINE TALLYING WS-TALLY FOR ALL "Mode: "
    ADD WS-TALLY TO WS-MODE-COUNT

    MOVE 0 TO WS-TALLY
    INSPECT LOG-LINE TALLYING WS-TALLY FOR ALL "HAILO_NOT_FOUND"
    ADD WS-TALLY TO WS-HAILO-ERR-COUNT

    MOVE 0 TO WS-TALLY
    INSPECT LOG-LINE TALLYING WS-TALLY FOR ALL "Traceback"
    ADD WS-TALLY TO WS-TRACEBACK-COUNT

    MOVE 0 TO WS-TALLY
    INSPECT LOG-LINE TALLYING WS-TALLY FOR ALL "Remote I/O error"
    ADD WS-TALLY TO WS-IO-ERR-COUNT

    MOVE 0 TO WS-TALLY
    INSPECT LOG-LINE TALLYING WS-TALLY FOR ALL "not connected"
    ADD WS-TALLY TO WS-DISCONNECT-COUNT.

PRINT-REPORT.
    DISPLAY "===================================================="
    DISPLAY " KIDA ROBOT -- RUN LOG SUMMARY (COBOL batch report)"
    DISPLAY "===================================================="
    DISPLAY " Source file      : " FUNCTION TRIM(WS-INPUT-PATH)
    MOVE WS-LINE-COUNT TO WS-DISPLAY-9
    DISPLAY " Lines processed  : " WS-DISPLAY-9
    DISPLAY "----------------------------------------------------"
    MOVE WS-STARTS-COUNT TO WS-DISPLAY-9
    DISPLAY " Session starts (restarts/crashes) : " WS-DISPLAY-9
    MOVE WS-MODE-COUNT TO WS-DISPLAY-9
    DISPLAY " Drive-mode changes                : " WS-DISPLAY-9
    MOVE WS-HAILO-ERR-COUNT TO WS-DISPLAY-9
    DISPLAY " Hailo HAILO_NOT_FOUND errors      : " WS-DISPLAY-9
    MOVE WS-TRACEBACK-COUNT TO WS-DISPLAY-9
    DISPLAY " Python tracebacks                 : " WS-DISPLAY-9
    MOVE WS-IO-ERR-COUNT TO WS-DISPLAY-9
    DISPLAY " I2C / Remote I-O errors           : " WS-DISPLAY-9
    MOVE WS-DISCONNECT-COUNT TO WS-DISPLAY-9
    DISPLAY " Arduino 'not connected' events    : " WS-DISPLAY-9
    DISPLAY "====================================================".
