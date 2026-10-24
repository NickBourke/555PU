; double.asm: show twice the value on the input switches, over and over
IN          ; A = switches, C = 0
ADD | IN    ; A = A + switches, C = carry (set if switches >= 8)
JMP 0
