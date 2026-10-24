LDI 13
ADD 5       ; 18 -> A = 2, C = 1
JC 5
LDI 15      ; skipped
JMP 3
ADD 0       ; clears C (2 + 0 has no carry)
JC 3; not taken
JMP 7       ; halt with A = 2, C = 0
    
