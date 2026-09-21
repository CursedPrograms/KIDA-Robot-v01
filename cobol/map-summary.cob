      >>SOURCE FORMAT FREE
*> map-summary.cob — batch summary across every 3D map mapper/build_3d_map.py
*> has built. Same "flat file in, structured report out" pattern as
*> kida-report.cob, since COBOL has no sqlite driver and no HailoRT
*> bindings — its role here is exactly what it's good at: reading a
*> concatenated stream of the *_stats.txt files build_3d_map.py already
*> writes per map, and tallying totals across all of them.
*>
*> One argument: the path to that concatenated stats stream — see
*> run_map_summary.sh, which cats mapper/output/*_stats.txt together.
IDENTIFICATION DIVISION.
PROGRAM-ID. MAP-SUMMARY.

ENVIRONMENT DIVISION.
INPUT-OUTPUT SECTION.
FILE-CONTROL.
    SELECT STATS-FILE ASSIGN TO WS-INPUT-PATH
        ORGANIZATION IS LINE SEQUENTIAL
        FILE STATUS IS WS-FILE-STATUS.

DATA DIVISION.
FILE SECTION.
FD  STATS-FILE.
01  STATS-LINE                  PIC X(500).

WORKING-STORAGE SECTION.
01  WS-INPUT-PATH                PIC X(256).
01  WS-FILE-STATUS               PIC XX.
01  WS-EOF                       PIC X VALUE "N".
    88  END-OF-FILE              VALUE "Y".

01  WS-MAP-COUNT                 PIC 9(9) VALUE 0.
01  WS-TOTAL-SWEEP-POINTS        PIC 9(9) VALUE 0.
01  WS-TOTAL-OUTPUT-POINTS       PIC 9(9) VALUE 0.

01  WS-KEY-TEXT                  PIC X(50).
01  WS-VALUE-TEXT                PIC X(500).
01  WS-VALUE-NUM                 PIC 9(9).

01  WS-DISPLAY-9                 PIC ZZZ,ZZZ,ZZ9.

PROCEDURE DIVISION.
MAIN-PARA.
    ACCEPT WS-INPUT-PATH FROM COMMAND-LINE
    IF WS-INPUT-PATH = SPACES
        DISPLAY "Usage: map-summary <concatenated-stats-path>"
        STOP RUN
    END-IF

    OPEN INPUT STATS-FILE
    IF WS-FILE-STATUS NOT = "00"
        DISPLAY "Could not open " FUNCTION TRIM(WS-INPUT-PATH)
            " (status " WS-FILE-STATUS ")"
        STOP RUN
    END-IF

    PERFORM UNTIL END-OF-FILE
        READ STATS-FILE
            AT END
                MOVE "Y" TO WS-EOF
            NOT AT END
                PERFORM COUNT-LINE
        END-READ
    END-PERFORM

    CLOSE STATS-FILE
    PERFORM PRINT-REPORT
    STOP RUN.

COUNT-LINE.
    IF STATS-LINE(1:10) = "sweep_id: "
        ADD 1 TO WS-MAP-COUNT
    END-IF

    IF STATS-LINE(1:14) = "sweep_points: "
        PERFORM EXTRACT-TRAILING-NUMBER
        ADD WS-VALUE-NUM TO WS-TOTAL-SWEEP-POINTS
    END-IF

    IF STATS-LINE(1:27) = "output_points_after_voxel_b"
        PERFORM EXTRACT-TRAILING-NUMBER
        ADD WS-VALUE-NUM TO WS-TOTAL-OUTPUT-POINTS
    END-IF.

EXTRACT-TRAILING-NUMBER.
    MOVE SPACES TO WS-KEY-TEXT
    MOVE SPACES TO WS-VALUE-TEXT
    UNSTRING STATS-LINE DELIMITED BY ": "
        INTO WS-KEY-TEXT WS-VALUE-TEXT
    MOVE 0 TO WS-VALUE-NUM
    IF FUNCTION TEST-NUMVAL(FUNCTION TRIM(WS-VALUE-TEXT)) = 0
        COMPUTE WS-VALUE-NUM = FUNCTION NUMVAL(FUNCTION TRIM(WS-VALUE-TEXT))
    END-IF.

PRINT-REPORT.
    DISPLAY "===================================================="
    DISPLAY " KIDA ROBOT -- 3D MAP SUMMARY (COBOL batch report)"
    DISPLAY "===================================================="
    MOVE WS-MAP-COUNT TO WS-DISPLAY-9
    DISPLAY " Maps built                        : " WS-DISPLAY-9
    MOVE WS-TOTAL-SWEEP-POINTS TO WS-DISPLAY-9
    DISPLAY " Total lidar sweep points logged   : " WS-DISPLAY-9
    MOVE WS-TOTAL-OUTPUT-POINTS TO WS-DISPLAY-9
    DISPLAY " Total 3D points across all maps   : " WS-DISPLAY-9
    DISPLAY "====================================================".
