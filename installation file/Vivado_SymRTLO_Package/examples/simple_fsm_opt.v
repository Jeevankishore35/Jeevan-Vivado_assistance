module simple_fsm (clk, rst, x, z);
  input clk, rst, x;
  output reg z;
  parameter S0 = 2'b00, S1 = 2'b01, S2 = 2'b10;
  reg [1:0] state, next_state;
  always @(posedge clk or posedge rst) begin
      if (rst) state <= S0; else state <= next_state;
  end
  always @(*) begin
      case (state)
        S0: begin
            next_state = (x ? S1 : S0);
            z = 0;
        end
        S1: begin
            next_state = (x ? S2 : S0);
            z = 0;
        end
        S2: begin
            next_state = (x ? S2 : S0);
            z = 1;
        end
    endcase
  end
endmodule