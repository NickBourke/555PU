LDI 9
ADD 15      ; A = A - 1, C = 0 only if A was already 0
JC 1
LDI 0       ; A went 0 -> 15; put it back
JMP 4       ; halt
    
